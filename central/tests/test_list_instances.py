import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import INSTANCE_PUBLIC_FIELDS, list_instances, registry
from central.central.doctype.asset.asset import Asset
from central.tests.test_iam import ensure_user

# Fields that must never leave the server. `list_instances` bypasses DocType
# RBAC (Atlas Instance is System Manager-only), so its allowlist is the only
# thing between a team member and the Atlas admin credentials.
SECRET_FIELDS = (
	"api_key",
	"api_secret",
	"base_url",
	"skip_tunnel",
	"tunnel_status",
	"tunnel_ip",
	"tunnel_url",
	"service_user",
	"peer_public_key",
	"peer_endpoint",
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
		if not frappe.db.exists("Atlas Instance", region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": region,
					"base_url": f"https://{region}.atlas.example.test",
					"status": status,
					"api_key": "admin-key",
					"api_secret": "admin-secret",
					"display_name": "Test City, Testland",
					"provider": "AWS",
					"country_code": "IN",
					"latitude": 19.07,
					"longitude": 72.87,
				}
			).insert()
		else:
			frappe.db.set_value("Atlas Instance", region, "status", status)
		return region

	def test_returns_exactly_the_public_allowlist(self):
		frappe.set_user(self.owner)
		rows = list_instances(team=self.team.name)

		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(set(row.keys()), set(INSTANCE_PUBLIC_FIELDS))
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
		Asset.mirror_vm(
			self.active_region,
			{
				"name": "li-registry-vm",
				"team": self.team.name,
				"title": "registry-vm",
				"status": "Stopped",
				"vcpus": 2,
				"memory_megabytes": 4096,
				"disk_gigabytes": 40,
				"frappe_version": "v15",
			},
		)
		frappe.set_user(self.owner)
		assets = registry(team=self.team.name)["assets"]

		self.assertEqual(len(assets), 1)
		for field in ("name", "resource_id", "plan", "resize_in_progress", "status", "cluster"):
			self.assertIn(field, assets[0])
		self.assertEqual(assets[0].name, assets[0].resource_id)
		self.assertEqual(assets[0].frappe_version, "v15")
