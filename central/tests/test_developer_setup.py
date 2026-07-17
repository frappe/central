from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.developer_setup import setup_local


class TestDeveloperSetup(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.original_developer_mode = frappe.conf.get("developer_mode")
		self.region = "local-dev-setup"
		self.addCleanup(self._cleanup)

	def _cleanup(self) -> None:
		frappe.conf.developer_mode = self.original_developer_mode
		frappe.set_user("Administrator")
		if frappe.db.exists("Atlas Instance", self.region):
			frappe.delete_doc("Atlas Instance", self.region, force=True, ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- cleanup rows committed by setup_local.

	def test_refuses_when_developer_mode_is_off(self) -> None:
		frappe.conf.developer_mode = 0
		with self.assertRaises(frappe.PermissionError):
			setup_local(seed_demo_data=0, register_atlas=0)

	def test_upserts_local_atlas_instance_without_registration(self) -> None:
		frappe.conf.developer_mode = 1
		out = setup_local(
			region=self.region,
			atlas_base_url="http://local-dev-setup.atlas.test",
			atlas_api_key="admin_key",
			atlas_api_secret="admin_secret",
			seed_demo_data=0,
			register_atlas=0,
		)

		instance = frappe.get_doc("Atlas Instance", self.region)
		self.assertEqual(instance.base_url, "http://local-dev-setup.atlas.test")
		self.assertEqual(instance.status, "Active")
		self.assertEqual(instance.skip_tunnel, 1)
		self.assertEqual(instance.api_key, "admin_key")
		self.assertEqual(instance.get_password("api_secret"), "admin_secret")
		self.assertEqual(out["atlas_instance"]["region"], self.region)
		self.assertEqual(out["demo_data"], "skipped")

	def test_register_delegates_to_atlas_instance(self) -> None:
		frappe.conf.developer_mode = 1
		with patch(
			"central.central.doctype.atlas_instance.atlas_instance.AtlasInstance.register",
			return_value={"ok": True, "tunnel_status": "Inactive", "skip_tunnel": True},
		) as register:
			out = setup_local(
				region=self.region,
				atlas_base_url="http://local-dev-setup.atlas.test",
				atlas_api_key="admin_key",
				atlas_api_secret="admin_secret",
				seed_demo_data=0,
				register_atlas=1,
			)

		register.assert_called_once()
		self.assertEqual(out["atlas_registration"]["ok"], True)
