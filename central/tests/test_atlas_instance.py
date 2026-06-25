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
				"api_key": "admin_k",
				"api_secret": "admin_s",
			}
		).insert()

	def test_admin_secret_is_stored_encrypted(self):
		inst = self.make_instance("blr-secret")
		# Plaintext is retrievable via get_password, but never stored in the column.
		self.assertEqual(inst.get_password("api_secret"), "admin_s")
		raw = frappe.db.get_value("Atlas Instance", inst.name, "api_secret")
		self.assertNotEqual(raw, "admin_s")

	def test_region_resolver(self):
		inst = self.make_instance("blr-resolve")
		self.assertEqual(get_atlas_instance("blr-resolve").name, inst.name)
		with self.assertRaises(AtlasError):
			get_atlas_instance("no-such-region")

	def test_client_uses_admin_token_over_base_url_then_tunnel(self):
		inst = self.make_instance("blr-auth")
		# Central→Atlas authenticates with the ADMIN token; before the tunnel is Active
		# the target is the public base_url.
		client = AtlasClient(inst).client()
		self.assertEqual(client.url, "https://atlas.example.test")
		self.assertEqual(client.api_key, "admin_k")
		self.assertEqual(client.api_secret, "admin_s")

		# Once Active, the data path is the tunnel_url over wg0 (validate() derives it).
		inst.tunnel_ip = "10.88.0.7"
		inst.tunnel_status = "Active"
		inst.save()
		self.assertEqual(AtlasClient(inst).client().url, "https://10.88.0.7")

	def test_disabled_instance_is_blocked(self):
		inst = self.make_instance("blr-auth-disabled")
		inst.status = "Disabled"
		inst.save()
		with self.assertRaises(AtlasError):
			AtlasClient(inst).client()
