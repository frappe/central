import frappe
import jwt
from frappe.tests import IntegrationTestCase

from central.api.sso import get_bench_link
from central.sso import _central_url, _ensure_oauth_client
from central.tests.test_iam import ensure_user


class TestCentralSSO(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# The shared-secret mint is dev-gated; enable the opt-in for these tests so
		# they don't depend on the site's config (CI's test_site has it off).
		self._orig_insecure = frappe.conf.get("sso_allow_insecure_hs256")
		frappe.conf.sso_allow_insecure_hs256 = 1
		self.owner = ensure_user("sso.owner@example.test")
		self.developer = ensure_user("sso.developer@example.test")
		self.viewer = ensure_user("sso.viewer@example.test")

	def tearDown(self):
		frappe.conf.sso_allow_insecure_hs256 = self._orig_insecure
		frappe.set_user("Administrator")

	def make_team(self, user: str, role: str):
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"SSO {role} Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": user, "role": role, "status": "Active"},
				],
			}
		).insert()

	def _verify_like_bench(self, token: str) -> dict:
		"""Decode exactly as admin/backend/auth.py:verify_assertion does."""
		client = _ensure_oauth_client()
		return jwt.decode(
			token,
			client.client_secret,
			algorithms=["HS256"],
			audience=client.client_id,
			issuer=_central_url(),
			options={"require": ["exp", "aud", "iss", "sub"]},
		)

	def test_mint_is_bench_verifiable_and_carries_only_bench_caps(self):
		team = self.make_team(self.developer, "Developer")
		frappe.set_user(self.developer)
		try:
			link = get_bench_link(team=team.name, gateway_url="http://localhost:3030")
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(link["url"].startswith("http://localhost:3030/sso?assertion="))
		claims = self._verify_like_bench(link["url"].split("assertion=", 1)[1])

		self.assertEqual(claims["sub"], self.developer)
		self.assertEqual(claims["team"], team.name)
		# Bench-plane caps only — never central/atlas caps. server:view is atlas
		# (the console-open gate lives in Central), so it never reaches the bench.
		self.assertIn("site:view", claims["caps"])
		self.assertIn("site:migrate", claims["caps"])
		self.assertNotIn("billing:view", claims["caps"])
		self.assertNotIn("server:view", claims["caps"])
		self.assertNotIn("server:create", claims["caps"])

	def test_production_site_refuses_shared_secret_mint(self):
		# Fail closed: without the explicit sso_allow_insecure_hs256 opt-in (i.e. a
		# prod site) the shared-secret mint must refuse until RS256 (#21) replaces it.
		team = self.make_team(self.developer, "Developer")
		original = frappe.conf.get("sso_allow_insecure_hs256")
		frappe.conf.sso_allow_insecure_hs256 = 0
		frappe.set_user(self.developer)
		try:
			with self.assertRaises(frappe.ValidationError):
				get_bench_link(team=team.name, gateway_url="http://localhost:3030")
		finally:
			frappe.conf.sso_allow_insecure_hs256 = original
			frappe.set_user("Administrator")

	def test_server_open_gates_the_handoff(self):
		# server:open (the old vm:open) is the console gate, distinct from server:view
		# which only lists servers. A Developer carries it and can open; a Viewer sees
		# servers in the inventory but cannot open the console.
		dev_team = self.make_team(self.developer, "Developer")
		frappe.set_user(self.developer)
		try:
			link = get_bench_link(team=dev_team.name, gateway_url="http://localhost:3030")
			self.assertIn("/sso?assertion=", link["url"])
		finally:
			frappe.set_user("Administrator")

		view_team = self.make_team(self.viewer, "Viewer")
		frappe.set_user(self.viewer)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_bench_link(team=view_team.name, gateway_url="http://localhost:3030")
		finally:
			frappe.set_user("Administrator")
