import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.atlas import AtlasClient, AtlasError, get_atlas_instance


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

	def test_client_carries_token_auth_and_disabled_is_blocked(self):
		inst = self.make_instance("blr-auth")
		client = AtlasClient(inst).client()
		self.assertEqual(client.url, "https://atlas.example.test")
		self.assertEqual(client.api_key, "key123")
		self.assertEqual(client.api_secret, "secret456")

		inst.status = "Disabled"
		inst.save()
		with self.assertRaises(AtlasError):
			AtlasClient(inst).client()
