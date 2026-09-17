import json
from copy import deepcopy
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import make_plan
from central.central.doctype.asset.asset import Asset
from central.errors import AtlasConnectionError, AtlasRequestUncertain
from central.integrations.server_provisioning import _process_locked, resolve_created_vm
from central.resource_actions import get_status
from central.server_provisioning import submit_request

COMPOSITION = [
	{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 1, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 20, "unit": "GB"},
]


class TestResourceActions(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.enqueue"))
		self.enterContext(patch("frappe.db.commit"))
		self.enterContext(patch.object(Asset, "ensure_subscription_enabled"))
		self.subscription = self.enterContext(
			patch("central.integrations.server_provisioning._create_subscription")
		)
		self.enterContext(
			patch(
				"central.integrations.server_provisioning.central_url",
				return_value="https://central.example.test",
			)
		)
		self.enterContext(
			patch(
				"central.integrations.server_provisioning.jwks_url",
				return_value="https://central.example.test/jwks",
			)
		)
		self.client = self.enterContext(patch("central.integrations.server_provisioning.AtlasClient"))
		self.observation = self.enterContext(
			patch("central.integrations.server_provisioning.observe_server", return_value="Running")
		)
		region = frappe.get_doc(
			{"doctype": "Region", "region": "action-" + frappe.generate_hash(length=8)}
		).insert()
		self.region = frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region.name,
				"base_url": "https://atlas.example.test",
				"status": "Active",
			}
		).insert()
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Actions", "owner_user": "Administrator"}
		).insert()
		self.plan = "action-plan-" + frappe.generate_hash(length=8)
		make_plan(
			self.plan, includes=deepcopy(COMPOSITION), rates=[{"cluster": "", "currency": "INR", "rate": 100}]
		)
		self.image = {
			"id": "pilot-image",
			"rootfs_size_mib": 8192,
			"tags": {"purpose": "pilot"},
		}
		self.enterContext(patch("central.server_provisioning.selected_image", return_value=self.image))
		self.purchase = self.enterContext(
			patch("central.server_provisioning.validate_purchase", return_value=(COMPOSITION, 100))
		)
		self.client.return_value.tenant_id = self.team.tenant_id
		self.client.return_value.create_vm.return_value = {"id": "vm-00001", "tenant_id": self.team.tenant_id}

	def submit(self, **changes):
		values = dict(
			team=self.team.name,
			region=self.region.name,
			title="My server",
			offering="pilot",
			image_id="pilot-image",
			request_key="request-key-00000001",
			plan=self.plan,
		)
		return submit_request(**{**values, **changes})

	def test_submission_is_durable_intent_without_remote_create(self):
		result = self.submit()
		self.assertEqual(result["status"], "Queued")
		self.client.return_value.create_vm.assert_not_called()
		action = frappe.get_doc("Resource Action", result["action"])
		self.assertEqual(action.get_configuration().virtual_cpu_count, 1)
		self.assertNotIn("central_auth_token", action.request_payload)

	def test_duplicate_key_returns_one_action_and_rejects_changed_input(self):
		first = self.submit()
		self.assertEqual(first["action"], self.submit()["action"])
		with self.assertRaises(frappe.ValidationError):
			self.submit(title="Different")
		self.purchase.assert_called_once()

	def test_success_bootstraps_pilot_without_saving_plaintext_token(self):
		name = self.submit()["action"]
		_process_locked(name)
		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Succeeded")
		self.assertEqual(action.remote_vm_id, "vm-00001")
		self.assertTrue(action.asset)
		payload = self.client.return_value.create_vm.call_args.args[0]
		credentials = json.loads(payload["metadata"]["pilot-central"])
		self.assertEqual(payload["metadata"]["central_action_id"], name)
		self.assertEqual(credentials["jwks_audience_id"], action.credential)
		self.assertNotIn(credentials["central_auth_token"], frappe.as_json(action.as_dict()))
		_process_locked(name)
		self.client.return_value.create_vm.assert_called_once()

	def test_lost_create_reply_is_not_redispatched(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		_process_locked(name)
		_process_locked(name)
		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Uncertain")
		self.assertEqual(action.error_code, "OUTCOME_UNKNOWN")
		self.assertFalse(action.retriable)
		self.assertFalse(action.remote_vm_id)
		self.client.return_value.create_vm.assert_called_once()

	def test_crash_after_dispatch_marker_is_uncertain(self):
		name = self.submit()["action"]
		frappe.db.set_value("Resource Action", name, "status", "Dispatching")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Uncertain")
		self.client.return_value.create_vm.assert_not_called()

	def test_lost_refresh_retains_acceptance_and_recovers_without_create(self):
		name = self.submit()["action"]
		self.observation.side_effect = AtlasConnectionError("read unavailable")
		_process_locked(name)
		self.assertEqual(get_status(name)["error"]["code"], "REFRESH_FAILED")
		self.observation.side_effect = None
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Succeeded")
		self.client.return_value.create_vm.assert_called_once()

	def test_revoked_permission_fails_before_dispatch(self):
		name = self.submit()["action"]
		with patch("central.integrations.server_provisioning.can", return_value=False):
			_process_locked(name)
		self.assertEqual(get_status(name)["error"]["code"], "PERMISSION_DENIED")
		self.client.return_value.create_vm.assert_not_called()

	def test_unknown_vm_binding_requires_matching_action_marker(self):
		name = self.submit()["action"]
		frappe.db.set_value("Resource Action", name, "status", "Uncertain")
		self.client.return_value.get_vm.return_value = {
			"id": "vm-00002",
			"tenant_id": self.team.tenant_id,
			"image_id": "pilot-image",
			"guest": {"metadata": {"central_action_id": "another-action"}},
		}
		with self.assertRaises(frappe.ValidationError):
			resolve_created_vm(name, "vm-00002")
		self.assertFalse(frappe.db.get_value("Resource Action", name, "remote_vm_id"))

	def test_cross_team_read_and_create_are_denied(self):
		name = self.submit()["action"]
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"action-{frappe.generate_hash(length=8)}@example.test",
				"first_name": "Action",
				"send_welcome_email": 0,
				"roles": [{"role": "Central User"}],
			}
		).insert()
		own = frappe.get_doc({"doctype": "Team", "team_name": "Other", "owner_user": user.name}).insert()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			get_status(name)
		with self.assertRaises(frappe.PermissionError):
			self.submit()
		self.assertEqual(frappe.get_list("Resource Action", filters={"team": self.team.name}), [])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Resource Action",
					"team": own.name,
					"resource_type": "Server",
					"action": "create",
					"correlation_id": frappe.generate_hash(),
				}
			).insert()

	def test_recovery_batch_does_not_starve_behind_unresolved_creates(self):
		from central.integrations.server_provisioning import recover_requests

		unknown = self.submit()["action"]
		queued = self.submit(request_key="second-request-key-001")["action"]
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-5)
		frappe.db.set_value(
			"Resource Action", unknown, {"status": "Uncertain", "modified": old}, update_modified=False
		)
		frappe.db.set_value("Resource Action", queued, "modified", old, update_modified=False)
		with patch(
			"central.central.doctype.resource_action.resource_action.ResourceAction.enqueue", autospec=True
		) as enqueue:
			recover_requests()
			names = [call.args[0].name for call in enqueue.call_args_list]
		self.assertIn(queued, names)
		self.assertNotIn(unknown, names)

	def test_unexpected_worker_failure_is_recorded_without_redispatch(self):
		from central.integrations.server_provisioning import process_request

		name = self.submit()["action"]
		with (
			patch(
				"central.integrations.server_provisioning._process_locked",
				side_effect=RuntimeError("worker failure"),
			),
			patch("frappe.db.rollback"),
			patch("frappe.log_error"),
		):
			process_request(name)
		self.assertEqual(get_status(name)["status"], "Failed")
		self.assertEqual(get_status(name)["error"]["code"], "UNEXPECTED")
		self.client.return_value.create_vm.assert_not_called()
