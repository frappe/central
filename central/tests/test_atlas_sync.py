from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import registry
from central.errors import AtlasConnectionError, AtlasRequestUncertain, AtlasResourceGone
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
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
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		self.cancel = self.enterContext(patch.object(VirtualMachine, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Actions", "owner_user": "Administrator"}
		).insert()
		ensure_atlas_instance("test-actions")
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "action-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"atlas_vm_id": "vm-00001",
				"region": "test-actions",
				"status": "Stopped",
			}
		).insert()
		self.client = self.enterContext(patch("central.integrations.servers._client")).return_value
		self.observe = self.enterContext(
			patch("central.integrations.servers.observe_server", return_value="Running")
		)

	def submit(self, action="start"):
		return submit_command(action, self.team.name, self.server.name)

	def test_start_persists_intent_before_dispatch_and_confirms_by_read(self):
		result = self.submit()
		self.assertEqual(result["status"], "Queued")
		self.client.vm_action.assert_not_called()
		_process_locked(result["action"])
		self.assertEqual(get_status(result["action"])["status"], "Succeeded")
		self.client.vm_action.assert_called_once_with("vm-00001", "start")

	def test_command_that_never_reaches_its_goal_times_out(self):
		name = self.submit("stop")["action"]
		_process_locked(name)
		frappe.db.set_value("Resource Action", name, "dispatched_at", "2020-01-01 00:00:00")

		_process_locked(name)

		self.assertEqual(frappe.db.get_value("Resource Action", name, "status"), "Timed Out")

	def test_duplicate_action_returns_existing_request(self):
		first = self.submit()
		self.assertEqual(self.submit()["action"], first["action"])
		with self.assertRaises(frappe.ValidationError):
			self.submit("stop")

	def test_create_and_resize_are_not_accepted_as_commands(self):
		"""Both carry a saved configuration that only their own intake validates."""
		for action in ("create", "resize"):
			with self.subTest(action=action), self.assertRaises(frappe.PermissionError):
				self.submit(action)
		self.assertFalse(frappe.db.exists("Resource Action", {"resource_id": self.server.name}))

	def test_restart_is_refused_unless_the_server_is_running(self):
		with self.assertRaises(frappe.ValidationError):
			self.submit("restart")
		self.enqueue.assert_not_called()

		self.server.db_set("status", "Running")
		self.assertEqual(self.submit("restart")["status"], "Queued")

	def test_restart_needs_evidence_that_it_left_running(self):
		self.server.db_set("status", "Running")
		name = self.submit("restart")["action"]

		_process_locked(name)
		self.client.vm_action.assert_called_once_with("vm-00001", "restart")
		self.assertEqual(get_status(name)["status"], "Sent")

		_process_locked(name)
		self.client.vm_action.assert_called_once()
		self.assertEqual(get_status(name)["status"], "Sent")

		frappe.get_doc("Resource Action", name).record_observed_status("Stopped")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Succeeded")

	def test_an_operator_can_ask_the_region_for_the_current_state(self):
		"""Desk needs a way to ask the region directly when a record looks stale."""
		self.assertEqual(self.server.sync_state(), {"status": "Running"})
		self.observe.assert_called_once()

	def test_start_is_blocked_while_resizing(self):
		frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "resize",
				"team": self.team.name,
				"region": self.server.region,
				"server": self.server.name,
				"resource_id": self.server.name,
				"remote_vm_id": self.server.atlas_vm_id,
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "Sent",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.submit()
		self.assertEqual(frappe.db.count("Resource Action", {"team": self.team.name}), 1)

	def test_cross_team_commands_and_registry_are_denied(self):
		frappe.set_user(ensure_user("action-outsider@example.test"))
		with self.assertRaises(frappe.PermissionError):
			self.submit()
		with self.assertRaises(frappe.PermissionError):
			registry(team=self.team.name)
		self.client.vm_action.assert_not_called()

	def test_revoked_permission_prevents_queued_command(self):
		name = self.submit()["action"]
		with patch("central.infrastructure.doctype.resource_action.resource_action.can", return_value=False):
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
		self.assertEqual(self.server.reload().status, "Terminated")
		self.cancel.assert_called_once()

	def test_start_fails_on_scoped_absence(self):
		name = self.submit()["action"]
		self.client.vm_action.side_effect = AtlasResourceGone("gone")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Failed")

	def test_refresh_enqueues_only_known_team_servers(self):
		self.enqueue.reset_mock()
		result = reconcile(self.team.name)
		self.assertEqual(result["queued"], 1)
		self.assertEqual(self.enqueue.call_args.kwargs["name"], self.server.name)
