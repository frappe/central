from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import registry
from central.central.doctype.asset.asset import Asset
from central.errors import AtlasConnectionError, AtlasRequestUncertain, AtlasResourceGone
from central.integrations.server_provisioning import _process_locked
from central.integrations.servers import reconcile
from central.resource_actions import get_status, submit_command
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestServerActions(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.db.commit"))
		self.enqueue = self.enterContext(patch("frappe.enqueue"))
		self.enterContext(patch.object(Asset, "ensure_subscription_enabled"))
		self.cancel = self.enterContext(patch.object(Asset, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Actions", "owner_user": "Administrator"}
		).insert()
		ensure_atlas_instance("test-actions")
		self.asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "action-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"atlas_vm_id": "vm-00001",
				"cluster": "test-actions",
				"status": "Stopped",
			}
		).insert()
		self.client = self.enterContext(patch("central.integrations.servers._client")).return_value
		self.observe = self.enterContext(
			patch("central.integrations.servers.observe_server", return_value="Running")
		)

	def submit(self, action="start"):
		return submit_command(action, self.team.name, self.asset.name)

	def test_start_persists_intent_before_dispatch_and_confirms_by_read(self):
		result = self.submit()
		self.assertEqual(result["status"], "Queued")
		self.client.vm_action.assert_not_called()
		_process_locked(result["action"])
		self.assertEqual(get_status(result["action"])["status"], "Succeeded")
		self.client.vm_action.assert_called_once_with("vm-00001", "start")

	def test_duplicate_action_returns_existing_request(self):
		first = self.submit()
		self.assertEqual(self.submit()["action"], first["action"])
		with self.assertRaises(frappe.ValidationError):
			self.submit("stop")

	def test_start_is_blocked_while_resizing(self):
		self.asset.db_set("resize_in_progress", 1)
		with self.assertRaises(frappe.ValidationError):
			self.submit()
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team.name}))

	def test_cross_team_commands_and_registry_are_denied(self):
		frappe.set_user(ensure_user("action-outsider@example.test"))
		with self.assertRaises(frappe.PermissionError):
			self.submit()
		with self.assertRaises(frappe.PermissionError):
			registry(team=self.team.name)
		self.client.vm_action.assert_not_called()

	def test_revoked_permission_prevents_queued_command(self):
		name = self.submit()["action"]
		with patch("central.integrations.servers.can", return_value=False):
			_process_locked(name)
		self.assertEqual(get_status(name)["error"]["code"], "PERMISSION_DENIED")
		self.client.vm_action.assert_not_called()

	def test_lost_command_reply_recovers_by_read_without_redispatch(self):
		name = self.submit()["action"]
		self.client.vm_action.side_effect = AtlasRequestUncertain("lost reply")
		self.observe.side_effect = AtlasConnectionError("offline")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Uncertain")
		self.observe.side_effect = None
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Succeeded")
		self.client.vm_action.assert_called_once()

	def test_accepted_command_waits_for_observed_target(self):
		name = self.submit()["action"]
		self.observe.return_value = "Stopped"
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "In Progress")
		self.observe.return_value = "Running"
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Succeeded")
		self.client.vm_action.assert_called_once()

	def test_terminate_succeeds_on_scoped_absence(self):
		name = self.submit("terminate")["action"]
		self.client.vm_action.side_effect = AtlasResourceGone("gone")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Succeeded")
		self.assertEqual(self.asset.reload().status, "Terminated")
		self.cancel.assert_called_once()

	def test_start_fails_on_scoped_absence(self):
		name = self.submit()["action"]
		self.client.vm_action.side_effect = AtlasResourceGone("gone")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Failed")

	def test_refresh_enqueues_only_known_team_mirrors(self):
		self.enqueue.reset_mock()
		result = reconcile(self.team.name)
		self.assertEqual(result["queued"], 1)
		self.assertEqual(self.enqueue.call_args.kwargs["name"], self.asset.name)
