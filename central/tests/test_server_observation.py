from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.asset.asset import Asset
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.errors import AtlasConnectionError, AtlasResourceGone
from central.integrations.servers import observe_server


class TestServerObservation(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(Asset, "ensure_subscription_enabled"))
		self.cancel_billing = self.enterContext(patch.object(Asset, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Mirror", "owner_user": "Administrator"}
		).insert()
		region = frappe.get_doc(
			{"doctype": "Region", "region": "mirror-" + frappe.generate_hash(length=8)}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region.name,
				"base_url": "https://atlas.example.test",
				"proxy_domain": "par-2.example.test",
				"status": "Active",
			}
		).insert()
		self.asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "server-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"cluster": region.name,
				"atlas_vm_id": "vm-00001",
				"status": "Provisioning",
			}
		).insert()
		self.client = self.enterContext(patch("central.integrations.servers.AtlasClient")).return_value
		self.client.tenant_id = self.team.tenant_id
		self.client.get_vm.return_value = {
			"id": "vm-00001",
			"tenant_id": self.team.tenant_id,
			"current_state": "running",
			"error": None,
			"compute": {"cpu_millicores": 1000, "memory_mib": 512},
			"disk": {"size_mib": 20480},
			"network": {"mesh_ipv6": "fdaa:1::1", "public_ipv4": None},
		}

	def test_observation_closes_the_action_waiting_for_that_state(self):
		action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "stop",
				"team": self.team.name,
				"atlas_instance": self.asset.cluster,
				"asset": self.asset.name,
				"resource_id": self.asset.name,
				"remote_vm_id": "vm-00001",
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "In Progress",
			}
		).insert(ignore_permissions=True)
		self.client.get_vm.return_value["current_state"] = "stopped"

		self.assertEqual(observe_server(self.asset), "Stopped")
		self.assertEqual(frappe.db.get_value("Resource Action", action.name, "status"), "Succeeded")

	def test_observation_preserves_local_and_regional_identity(self):
		self.assertEqual(observe_server(self.asset), "Running")
		self.asset.reload()
		self.assertEqual(self.asset.atlas_vm_id, "vm-00001")
		self.assertEqual(self.asset.memory_megabytes, 512)
		self.assertTrue(self.asset.name.startswith("server-"))
		self.client.get_vm.assert_called_once_with("vm-00001")

	def test_gateway_waits_for_an_enrolled_pilot(self):
		self.assertEqual(observe_server(self.asset), "Running")
		self.assertIsNone(self.asset.reload().gateway_url)

		PilotCredential.mint(
			team=self.team.name, pilot_credential_id="pcred-" + self.asset.name, asset=self.asset.name
		)
		observe_server(self.asset)
		self.assertEqual(self.asset.reload().gateway_url, "https://admin-vm-1z141z4.par-2.example.test")

	def test_read_failure_never_means_terminated(self):
		self.client.get_vm.side_effect = AtlasConnectionError("unreachable")
		with self.assertRaises(AtlasConnectionError):
			observe_server(self.asset)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Provisioning")

	def test_scoped_absence_terminates_and_runs_billing_hook(self):
		self.client.get_vm.side_effect = AtlasResourceGone("gone")
		self.assertEqual(observe_server(self.asset), "Terminated")
		self.asset.reload()
		self.assertEqual(self.asset.status, "Terminated")
		self.cancel_billing.assert_called_once()

	def test_cross_tenant_response_is_rejected_without_changing_the_record(self):
		self.client.get_vm.return_value["tenant_id"] += 1
		with self.assertRaises(AtlasConnectionError):
			observe_server(self.asset)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Provisioning")

	def test_older_report_cannot_regress_state(self):
		now = frappe.utils.now_datetime()
		self.asset.db_set({"status": "Running", "state_observed_at": now})

		applied = Asset.record_observed_state(
			self.asset.name, frappe.utils.add_to_date(now, seconds=-1), {"status": "Stopped"}
		)
		self.assertFalse(applied)
		self.assertEqual(self.asset.reload().status, "Running")

	def test_report_for_an_unknown_server_is_ignored(self):
		self.assertFalse(Asset.record_observed_state("server-absent", None, {"status": "Stopped"}))

	def test_report_writes_only_the_fields_it_carries(self):
		self.asset.db_set({"public_ipv4": "203.0.113.7"})

		self.assertTrue(
			Asset.record_observed_state(self.asset.name, frappe.utils.now_datetime(), {"status": "Stopped"})
		)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Stopped")
		self.assertEqual(self.asset.public_ipv4, "203.0.113.7")

	def test_report_never_touches_a_field_Central_owns(self):
		self.asset.db_set({"title": "acme-1", "plan": None})

		Asset.record_observed_state(
			self.asset.name,
			frappe.utils.now_datetime(),
			{"status": "Running", "title": "vm-00001", "team": "another-team"},
		)
		self.asset.reload()
		self.assertEqual(self.asset.title, "acme-1")
		self.assertEqual(self.asset.team, self.team.name)

	def test_a_recorded_report_reaches_only_the_owning_team(self):
		"""The console learns about its own servers through its team's room, so one
		team's traffic never reaches another's browser."""
		with patch("frappe.publish_realtime") as published:
			Asset.record_observed_state(self.asset.name, frappe.utils.now_datetime(), {"status": "Stopped"})

		# Frappe's own save() also publishes doc_update and list_update for Desk.
		published.assert_any_call(
			"server_state_changed",
			{"resource_id": self.asset.name},
			doctype="Team",
			docname=self.team.name,
			after_commit=True,
		)

	def test_a_report_that_changes_nothing_wakes_no_console(self):
		now = frappe.utils.now_datetime()
		self.asset.db_set({"state_observed_at": now})

		with patch("frappe.publish_realtime") as published:
			Asset.record_observed_state(
				self.asset.name, frappe.utils.add_to_date(now, seconds=-1), {"status": "Stopped"}
			)
			Asset.record_observed_state("server-absent", now, {"status": "Stopped"})

		self.assertNotIn(
			"server_state_changed", [call.args[0] for call in published.call_args_list if call.args]
		)

	def test_record_locks_before_loading(self):
		with patch("frappe.get_doc", wraps=frappe.get_doc) as get_doc:
			Asset.record_observed_state(self.asset.name, frappe.utils.now_datetime(), {"status": "Stopped"})
		self.assertTrue(
			any(
				call.args == ("Asset", self.asset.name) and call.kwargs.get("for_update")
				for call in get_doc.call_args_list
			)
		)
