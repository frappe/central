import frappe
import jwt
from frappe.tests import IntegrationTestCase

from central.sso import _central_url, _ensure_oauth_client, get_bench_link
from central.tests.test_iam import ensure_user


class TestOpenBench(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._orig = frappe.conf.get("sso_allow_insecure_hs256")
		frappe.conf.sso_allow_insecure_hs256 = 1
		self.owner = ensure_user("open.owner@example.test")
		self.dev = ensure_user("open.dev@example.test")
		self.viewer = ensure_user("open.viewer@example.test")
		self.team = self._team()
		self.cluster = self._cluster("blr-open")
		self.asset = self._asset("vm-open-1", "Running", "http://localhost:3030")

	def tearDown(self):
		frappe.conf.sso_allow_insecure_hs256 = self._orig
		frappe.set_user("Administrator")

	def _team(self):
		name = "Open Bench Team"
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
			frappe.delete_doc("Team", existing, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": name,
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.dev, "role": "Developer", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()

	def _cluster(self, region):
		if frappe.db.exists("Atlas Instance", region):
			frappe.delete_doc("Atlas Instance", region, force=True)
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
				"api_key": "k",
				"api_secret": "s",
			}
		).insert()
		return region

	def _asset(self, rid, status, gateway):
		if frappe.db.exists("Asset", rid):
			frappe.delete_doc("Asset", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": rid,
				"team": self.team.name,
				"cluster": self.cluster,
				"status": status,
				"gateway_url": gateway or None,
			}
		).insert(ignore_permissions=True)

	def _verify(self, token):
		client = _ensure_oauth_client()
		return jwt.decode(
			token,
			client.client_secret,
			algorithms=["HS256"],
			audience=client.client_id,
			issuer=_central_url(),
			options={"require": ["exp", "aud", "iss", "sub"]},
		)

	def _as(self, user, fn):
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	def test_open_running_vm_mints_for_its_gateway(self):
		link = self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
		self.assertTrue(link["url"].startswith("http://localhost:3030/sso?assertion="))
		claims = self._verify(link["url"].split("assertion=", 1)[1])
		self.assertEqual(claims["sub"], self.dev)
		self.assertEqual(claims["team"], self.team.name)

	def test_viewer_without_vm_open_is_blocked(self):
		with self.assertRaises(frappe.PermissionError):
			self._as(self.viewer, lambda: get_bench_link(asset="vm-open-1"))

	def test_stopped_vm_refused(self):
		self._asset("vm-open-1", "Stopped", "http://localhost:3030")
		with self.assertRaises(frappe.ValidationError):
			self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))

	def test_missing_gateway_refused(self):
		self._asset("vm-open-1", "Running", "")
		with self.assertRaises(frappe.ValidationError):
			self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))

	def test_disabled_cluster_refused(self):
		frappe.db.set_value("Atlas Instance", self.cluster, "status", "Disabled")
		with self.assertRaises(frappe.ValidationError):
			self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
