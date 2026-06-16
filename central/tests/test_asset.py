from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.atlas_client import INVENTORY_VM_FIELDS, AtlasClient, stub_vm_inventory
from central.tests.test_iam import ensure_user


class TestAsset(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("asset.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Asset Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.cluster = "blr-asset"
		if not frappe.db.exists("Atlas Instance", self.cluster):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.cluster,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()

	def test_asset_named_by_resource_id_and_links(self):
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "vm-xyz",
				"team": self.team.name,
				"cluster": self.cluster,
				"status": "Running",
				"gateway_url": "http://localhost:3030",
			}
		).insert()
		self.assertEqual(asset.name, "vm-xyz")
		self.assertEqual(asset.team, self.team.name)
		self.assertEqual(asset.cluster, self.cluster)

	def test_inventory_stub_matches_contract_shape(self):
		vms = stub_vm_inventory(self.team.name)
		self.assertTrue(vms)
		for vm in vms:
			self.assertEqual(set(vm.keys()), set(INVENTORY_VM_FIELDS))

	def test_list_vms_calls_team_scoped_endpoint(self):
		inst = frappe.get_doc("Atlas Instance", self.cluster)
		with patch("central.atlas_client.requests.request") as req:
			req.return_value.json.return_value = []
			req.return_value.raise_for_status.return_value = None
			AtlasClient(inst).list_vms(self.team.name)
			_, kwargs = req.call_args
			self.assertEqual(kwargs["params"], {"team": self.team.name})
			self.assertTrue(req.call_args[0][1].endswith("/api/method/atlas.api.list_team_vms"))
