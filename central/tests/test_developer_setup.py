from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.developer_setup import setup_local


class TestDeveloperSetup(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.previous = frappe.conf.developer_mode
		self.addCleanup(setattr, frappe.conf, "developer_mode", self.previous)
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.db.commit"))
		frappe.set_user("Administrator")

	def test_requires_developer_mode(self):
		frappe.conf.developer_mode = 0
		with self.assertRaises(frappe.PermissionError):
			setup_local(seed_demo_data=0)

	def test_signed_region_setup_and_check(self):
		frappe.conf.developer_mode = 1
		with patch(
			"central.central.doctype.region.region.Region.test_connection",
			return_value={"reachable": True},
		) as check:
			result = setup_local(
				region="dev-" + frappe.generate_hash(length=8),
				atlas_base_url="http://blr.atlas.localhost:8001",
				atlas_region_id="0",
				seed_demo_data=0,
			)
		check.assert_called_once()
		self.assertEqual(result["atlas_instance"]["atlas_region_id"], "0")
		self.assertTrue(result["atlas_connection"]["reachable"])
