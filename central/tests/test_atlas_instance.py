from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.atlas_client import AtlasClient, AtlasError, get_atlas_instance


class TestAtlasInstance(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def make_instance(self, region: str, status: str = "Active"):
		if frappe.db.exists("Atlas Instance", region):
			frappe.delete_doc("Atlas Instance", region, force=True)
		return frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": status,
				"api_key": "key123",
				"api_secret": "secret456",
			}
		).insert()

	def test_secret_is_stored_encrypted(self):
		inst = self.make_instance("blr-secret")
		# Plaintext is retrievable via get_password, but never stored in the column.
		self.assertEqual(inst.get_password("api_secret"), "secret456")
		raw = frappe.db.get_value("Atlas Instance", inst.name, "api_secret")
		self.assertNotEqual(raw, "secret456")

	def test_region_resolver(self):
		inst = self.make_instance("blr-resolve")
		self.assertEqual(get_atlas_instance("blr-resolve").name, inst.name)
		with self.assertRaises(AtlasError):
			get_atlas_instance("no-such-region")

	def test_request_sends_token_auth_and_disabled_is_blocked(self):
		inst = self.make_instance("blr-auth")
		with patch("central.atlas_client.requests.request") as req:
			req.return_value.json.return_value = {"message": "pong"}
			req.return_value.raise_for_status.return_value = None
			AtlasClient(inst).ping()
			_, kwargs = req.call_args
			self.assertEqual(kwargs["headers"]["Authorization"], "token key123:secret456")
			self.assertEqual(req.call_args[0][1], "https://atlas.example.test/api/method/ping")

		inst.status = "Disabled"
		inst.save()
		with self.assertRaises(AtlasError):
			AtlasClient(inst).ping()
