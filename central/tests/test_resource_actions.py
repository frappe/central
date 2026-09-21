import json
from copy import deepcopy
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import make_plan
from central.central.doctype.asset.asset import Asset
from central.central.doctype.resource_action.resource_action import ResourceAction
from central.errors import AtlasConnectionError, AtlasRequestUncertain
from central.integrations.server_provisioning import _process_locked
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
		self.region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "action-" + frappe.generate_hash(length=8),
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

	def test_a_paid_server_never_sleeps_and_carries_the_signing_keys(self):
		name = self.submit()["action"]
		_process_locked(name)

		payload = self.client.return_value.create_vm.call_args.args[0]
		self.assertEqual(payload["sleep_after_idle_seconds"], 0)
		credentials = json.loads(payload["metadata"]["pilot-central"])
		self.assertIn("keys", credentials["initial_jwks_cache"])

	def test_a_trial_server_sleeps_after_the_configured_idle_time(self):
		frappe.db.set_value("Team", self.team.name, "is_staging_trial", 1)
		frappe.db.set_single_value("Central Settings", "trial_idle_shutdown_minutes", 45)
		frappe.clear_cache(doctype="Central Settings")
		name = self.submit()["action"]
		_process_locked(name)

		payload = self.client.return_value.create_vm.call_args.args[0]
		self.assertEqual(payload["sleep_after_idle_seconds"], 45 * 60)

	def test_a_zero_idle_time_keeps_a_trial_server_awake(self):
		frappe.db.set_value("Team", self.team.name, "is_staging_trial", 1)
		frappe.db.set_single_value("Central Settings", "trial_idle_shutdown_minutes", 0)
		frappe.clear_cache(doctype="Central Settings")
		name = self.submit()["action"]
		_process_locked(name)

		self.assertEqual(self.client.return_value.create_vm.call_args.args[0]["sleep_after_idle_seconds"], 0)

	def test_a_repeated_request_under_a_new_key_returns_the_saved_one(self):
		first = self.submit()
		self.assertEqual(self.submit(request_key="lost-reply-key-000001")["action"], first["action"])
		self.assertEqual(frappe.db.count("Resource Action", {"team": self.team.name}), 1)

	def test_a_different_server_is_its_own_request_while_one_is_pending(self):
		first = self.submit()
		second = self.submit(request_key="second-request-key-001", title="Second server")
		self.assertNotEqual(first["action"], second["action"])

	def test_site_name_and_resource_type_are_part_of_the_request_identity(self):
		first = self.submit(resource_type="Site", subdomain="alpha")
		second = self.submit(
			request_key="second-request-key-001",
			resource_type="Site",
			subdomain="beta",
		)
		server = self.submit(request_key="third-request-key-0001")

		self.assertNotEqual(first["action"], second["action"])
		self.assertNotEqual(first["action"], server["action"])

	def test_an_answered_request_does_not_absorb_a_later_one(self):
		first = self.submit()["action"]
		_process_locked(first)
		second = self.submit(request_key="second-request-key-001")["action"]
		self.assertNotEqual(first, second)

	def test_open_creations_carry_a_request_that_has_no_server_yet(self):
		name = self.submit()["action"]
		[creation] = ResourceAction.open_creations(self.team.name)
		self.assertEqual(creation["action"], name)
		self.assertIsNone(creation["resource_id"])
		self.assertEqual(creation["requested_by"], "Administrator")
		self.assertEqual(ResourceAction.pending_labels(self.team.name), {})

	def test_open_creations_drop_a_request_that_finished(self):
		name = self.submit()["action"]
		_process_locked(name)
		self.assertEqual(ResourceAction.open_creations(self.team.name), [])

	def test_retry_redrives_the_same_record_without_a_second_create(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasConnectionError("region refused")
		_process_locked(name)
		self.assertEqual(get_status(name)["status"], "Failed")

		self.client.return_value.create_vm.side_effect = None
		self.assertEqual(frappe.get_doc("Resource Action", name).retry()["status"], "Queued")
		_process_locked(name)
		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Succeeded")
		self.assertIsNone(action.error_code)
		self.assertEqual(action.remote_vm_id, "vm-00001")
		# One record and one accepted machine. The first dispatch never reached a region,
		# so sending it again is the retry, not a second server.
		self.assertEqual(frappe.db.count("Resource Action", {"team": self.team.name}), 1)
		self.assertEqual(frappe.db.count("Asset", {"team": self.team.name}), 1)
		self.assertEqual(self.client.return_value.create_vm.call_count, 2)

	def test_retry_is_refused_without_a_saved_configuration(self):
		name = self.submit()["action"]
		frappe.db.set_value("Resource Action", name, {"status": "Failed", "request_payload": None})
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Resource Action", name).retry()

	def test_retry_is_refused_once_a_region_accepted_a_machine(self):
		name = self.submit()["action"]
		_process_locked(name)
		frappe.db.set_value("Resource Action", name, "status", "Failed")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Resource Action", name).retry()

	def test_retry_is_refused_while_the_request_is_still_running(self):
		name = self.submit()["action"]
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Resource Action", name).retry()
		self.client.return_value.create_vm.assert_not_called()

	def test_retry_rechecks_the_budget_before_spending_again(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasConnectionError("region refused")
		_process_locked(name)

		self.purchase.side_effect = frappe.ValidationError("Over the spending limit.")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Resource Action", name).retry()
		self.assertEqual(get_status(name)["status"], "Failed")

	def test_success_bootstraps_pilot_without_saving_plaintext_token(self):
		name = self.submit()["action"]
		_process_locked(name)
		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Succeeded")
		self.assertEqual(action.remote_vm_id, "vm-00001")
		self.assertTrue(action.asset)
		payload = self.client.return_value.create_vm.call_args.args[0]
		self.assertEqual(payload["cpu_millicores"], 1000)
		self.assertEqual(payload["firewall"], {"enabled": False})
		credentials = json.loads(payload["metadata"]["pilot-central"])
		self.assertEqual(payload["metadata"]["central_action_id"], name)
		self.assertEqual(credentials["jwks_audience_id"], action.credential)
		self.assertNotIn(credentials["central_auth_token"], frappe.as_json(action.as_dict()))
		_process_locked(name)
		self.client.return_value.create_vm.assert_called_once()

	def lose_the_reply(self, built: list[dict] | None = None) -> str:
		"""Dispatch a creation whose reply never arrives, and say what the region holds."""
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		self.client.return_value.list_vms.return_value = built or []
		_process_locked(name)
		return name

	def built_vm(self, name: str, **changes) -> dict:
		"""What the region reports for a machine this creation built."""
		self.client.return_value.get_vm.return_value = {
			"id": "vm-00009",
			"tenant_id": self.team.tenant_id,
			"image_id": "pilot-image",
			"guest": {"metadata": {"central_action_id": name}},
			**changes,
		}
		return {"id": "vm-00009", "created_at": int(frappe.utils.now_datetime().timestamp())}

	def test_a_lost_reply_finds_the_machine_it_built(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		self.client.return_value.list_vms.return_value = [self.built_vm(name)]
		_process_locked(name)

		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.remote_vm_id, "vm-00009")
		self.assertEqual(action.status, "Succeeded")
		self.client.return_value.create_vm.assert_called_once()

	def test_a_lost_reply_that_built_nothing_is_a_retriable_failure(self):
		name = self.lose_the_reply()

		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Failed")
		self.assertEqual(action.error_code, "CREATE_NOT_ACCEPTED")
		self.assertTrue(action.retriable)
		self.assertFalse(action.remote_vm_id)
		self.client.return_value.create_vm.assert_called_once()

	def test_an_unreachable_region_never_calls_a_creation_failed(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		self.client.return_value.list_vms.side_effect = AtlasConnectionError("region down")
		_process_locked(name)

		action = frappe.get_doc("Resource Action", name)
		self.assertEqual(action.status, "Uncertain")
		self.assertEqual(action.error_code, "OUTCOME_UNKNOWN")
		self.assertFalse(action.retriable)

	def test_another_requests_machine_is_never_adopted(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		self.client.return_value.list_vms.return_value = [self.built_vm("another-action")]
		_process_locked(name)

		action = frappe.get_doc("Resource Action", name)
		self.assertFalse(action.remote_vm_id)
		self.assertEqual(action.status, "Failed")

	def test_a_machine_older_than_the_dispatch_is_not_searched(self):
		name = self.submit()["action"]
		self.client.return_value.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		older = {"id": "vm-00001", "created_at": int(frappe.utils.now_datetime().timestamp()) - 3600}
		self.client.return_value.list_vms.return_value = [older]
		_process_locked(name)

		self.assertEqual(frappe.db.get_value("Resource Action", name, "status"), "Failed")
		self.client.return_value.get_vm.assert_not_called()

	def test_a_crash_after_the_dispatch_marker_settles_by_lookup(self):
		"""A replacement worker cannot know whether the first one reached the region, so it
		asks instead of sending again."""
		name = self.submit()["action"]
		frappe.db.set_value("Resource Action", name, "status", "Dispatching")
		self.client.return_value.list_vms.return_value = []
		_process_locked(name)

		self.assertEqual(get_status(name)["status"], "Failed")
		self.assertEqual(get_status(name)["error"]["code"], "CREATE_NOT_ACCEPTED")
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

	def test_the_recovery_sweep_picks_up_an_unanswered_creation(self):
		"""An unanswered creation settles itself now, so the sweep must reach it."""
		from central.integrations.server_provisioning import recover_requests

		unanswered = self.submit()["action"]
		queued = self.submit(request_key="second-request-key-001", title="Second server")["action"]
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-5)
		frappe.db.set_value(
			"Resource Action", unanswered, {"status": "Uncertain", "modified": old}, update_modified=False
		)
		frappe.db.set_value("Resource Action", queued, "modified", old, update_modified=False)
		with patch(
			"central.central.doctype.resource_action.resource_action.ResourceAction.enqueue", autospec=True
		) as enqueue:
			recover_requests()
			names = [call.args[0].name for call in enqueue.call_args_list]
		self.assertIn(queued, names)
		self.assertIn(unanswered, names)

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
