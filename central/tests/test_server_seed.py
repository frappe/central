import frappe
from frappe.tests import IntegrationTestCase

from central.demo.servers import ASSETS, REGIONS, _seed_resource_ids, seed, summary, teardown


class TestServerSeed(IntegrationTestCase):
	"""The demo fleet seed commits real rows, so every test restores the site by
	running teardown() in cleanup (mirroring how developer_setup tests handle
	their committed bootstrap rows)."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.original_developer_mode = frappe.conf.get("developer_mode")
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.set_user("Administrator")
		frappe.conf.developer_mode = 1
		teardown()
		frappe.conf.developer_mode = self.original_developer_mode

	def test_refuses_without_developer_mode(self):
		frappe.conf.developer_mode = 0
		with self.assertRaises(frappe.PermissionError):
			seed()
		with self.assertRaises(frappe.PermissionError):
			teardown()

	def test_seed_is_idempotent(self):
		frappe.conf.developer_mode = 1
		first = seed()
		second = seed()

		self.assertEqual(first, second)
		self.assertEqual(first["atlas_instances"], len(REGIONS))
		self.assertEqual(first["assets"], len(ASSETS))
		# Only Running assets carry a billing contract (Asset.on_update).
		running = sum(1 for row in ASSETS if row[3] == "Running")
		self.assertEqual(first["subscriptions"], running)
		# Every seeded VM records the version it was "provisioned" with.
		versions = frappe.get_all(
			"Asset", filters={"name": ["in", _seed_resource_ids()]}, pluck="frappe_version"
		)
		self.assertTrue(all(versions))

	def test_teardown_removes_all_seeded_rows(self):
		frappe.conf.developer_mode = 1
		seed()
		teardown()

		leftovers = summary()
		self.assertEqual(leftovers["atlas_instances"], 0)
		self.assertEqual(leftovers["assets"], 0)
		self.assertEqual(leftovers["subscriptions"], 0)
		self.assertFalse(
			frappe.get_all("Subscription", filters={"asset_id": ["in", _seed_resource_ids()]})
		)
