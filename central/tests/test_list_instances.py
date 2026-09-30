import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import REGION_LIST_FIELDS, list_instances, registry
from central.tests.test_iam import ensure_user

# The exact key set list_instances returns: the non-secret fields of an Active Region.
PUBLIC_FIELDS = REGION_LIST_FIELDS

# Fields that must never leave the server. `list_instances` bypasses DocType RBAC
# (Region is System Manager-only), so reading only the allowlist above is what
# keeps Atlas's admin credentials off the wire.
SECRET_FIELDS = (
	"base_url",
	"atlas_region_id",
	"proxy_domain",
	"webhook_secret",
	"connection_checked_at",
	"connection_error",
	"last_synced_at",
)


class TestListInstances(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("instances.owner@example.test")
		self.outsider = ensure_user("instances.outsider@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Instances Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.active_region = self._ensure_instance("li-active-test", "Active")
		self.draining_region = self._ensure_instance("li-draining-test", "Draining")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _ensure_instance(self, region: str, status: str) -> str:
		if not frappe.db.exists("Region", region):
			frappe.get_doc(
				{
					"doctype": "Region",
					"region": region,
					"display_name": "Test City, Testland",
					"provider": "AWS",
					"country_code": "IN",
					"latitude": 19.07,
					"longitude": 72.87,
					"base_url": f"https://{region}.atlas.example.test",
					"status": status,
				}
			).insert()
		else:
			frappe.db.set_value("Region", region, "status", status)
		return region

	def test_returns_exactly_the_public_allowlist(self):
		frappe.set_user(self.owner)
		rows = list_instances(team=self.team.name)

		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(set(row.keys()), set(PUBLIC_FIELDS))
			for field in SECRET_FIELDS:
				self.assertNotIn(field, row)

		ours = next(row for row in rows if row.region == self.active_region)
		self.assertEqual(ours.display_name, "Test City, Testland")
		self.assertEqual(ours.provider, "AWS")
		self.assertEqual(ours.country_code, "IN")
		self.assertAlmostEqual(ours.latitude, 19.07)
		self.assertAlmostEqual(ours.longitude, 72.87)

	def test_excludes_non_active_instances(self):
		frappe.set_user(self.owner)
		regions = [row.region for row in list_instances(team=self.team.name)]
		self.assertIn(self.active_region, regions)
		self.assertNotIn(self.draining_region, regions)

	def test_non_member_is_refused(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			list_instances(team=self.team.name)

	def test_registry_returns_console_fields(self):
		frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "li-registry-vm",
				"team": self.team.name,
				"region": self.active_region,
				"title": "registry-vm",
				"status": "Stopped",
				"vcpus": 2,
				"memory_megabytes": 4096,
				"disk_gigabytes": 40,
				"frappe_version": "v15",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.owner)
		servers = registry(team=self.team.name)["servers"]

		self.assertEqual(len(servers), 1)
		for field in ("name", "resource_id", "plan", "status", "region"):
			self.assertIn(field, servers[0])
		self.assertEqual(servers[0].name, servers[0].resource_id)
		self.assertEqual(servers[0].frappe_version, "v15")
