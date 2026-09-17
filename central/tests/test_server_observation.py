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
			"compute": {"vcpus": 1, "memory_mib": 512},
			"disk": {"size_mib": 20480},
			"network": {"mesh_ipv6": "fdaa:1::1", "public_ipv4": None},
		}

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

	def test_cross_tenant_response_is_rejected_without_changing_mirror(self):
		self.client.get_vm.return_value["tenant_id"] += 1
		with self.assertRaises(AtlasConnectionError):
			observe_server(self.asset)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Provisioning")

	def test_older_mirror_event_cannot_regress_state(self):
		now = frappe.utils.now_datetime()
		self.asset.db_set({"status": "Running", "last_event_at": now})
		Asset.mirror_vm(
			self.asset.cluster,
			{"name": self.asset.name, "team": self.team.name, "status": "Stopped"},
			occurred_at=frappe.utils.add_to_date(now, seconds=-1),
		)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Running")

	def test_mirror_recovers_when_exists_check_loses_insert_race(self):
		real_exists = frappe.db.exists

		def missing_asset(doctype, *args, **kwargs):
			return None if doctype == "Asset" else real_exists(doctype, *args, **kwargs)

		with patch("frappe.db.exists", side_effect=missing_asset):
			Asset.mirror_vm(
				self.asset.cluster, {"name": self.asset.name, "team": self.team.name, "status": "Stopped"}
			)
		self.asset.reload()
		self.assertEqual(self.asset.status, "Stopped")

	def test_mirror_update_locks_before_loading(self):
		with patch("frappe.get_doc", wraps=frappe.get_doc) as get_doc:
			Asset.mirror_vm(
				self.asset.cluster, {"name": self.asset.name, "team": self.team.name, "status": "Stopped"}
			)
		self.assertTrue(
			any(
				call.args == ("Asset", self.asset.name) and call.kwargs.get("for_update")
				for call in get_doc.call_args_list
			)
		)
