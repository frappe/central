import frappe
import jwt
from frappe.tests import IntegrationTestCase
from jwt.algorithms import RSAAlgorithm

from central.api.jwks import jwks_document
from central.api.sso import DEV_AUDIENCE, get_bench_link
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM
from central.sso import central_url
from central.tests.test_iam import ensure_user


class TestCentralSSO(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("sso.owner@example.test")
		self.developer = ensure_user("sso.developer@example.test")
		self.viewer = ensure_user("sso.viewer@example.test")

	def tearDown(self):
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

	def _verify_like_bench(self, token: str, audience: str) -> dict:
		"""Verify exactly as a bench would: reconstruct the public key from Central's JWKS
		and check the signature, audience, and issuer."""
		public_key = RSAAlgorithm.from_jwk(jwks_document()["keys"][0])
		return jwt.decode(
			token,
			public_key,
			algorithms=[ALGORITHM],
			audience=audience,
			issuer=central_url(),
			options={"require": ["exp", "aud", "iss", "sub"]},
		)

	def _open(self, user: str, **kwargs) -> dict:
		frappe.set_user(user)
		try:
			return get_bench_link(**kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_dev_gateway_mint_is_bench_verifiable(self):
		team = self.make_team(self.developer, "Developer")
		link = self._open(self.developer, team=team.name, gateway_url="http://localhost:3030")

		self.assertTrue(link["url"].startswith("http://localhost:3030/?sid="))
		claims = self._verify_like_bench(link["url"].split("sid=", 1)[1], DEV_AUDIENCE)
		self.assertEqual(claims["sub"], "admin")
		self.assertEqual(claims["scope"], "bench")
		self.assertEqual(claims["aud"], DEV_AUDIENCE)

	def test_bootstrap_verifier_rejects_other_scopes(self):
		# scope is an asserted claim, not a convention: bench-login and metrics tokens
		# are signed with the same key, so only the scope check stops one from being
		# accepted as an enrollment token.
		from central.sso import (
			mint_bench_login,
			mint_bootstrap_token,
			mint_metrics_token,
			verify_bootstrap_token,
		)

		enroll = mint_bootstrap_token("team-x", "pcred-x")
		self.assertEqual(verify_bootstrap_token(enroll)["team"], "team-x")

		for other in (mint_bench_login("pcred-x"), mint_metrics_token("pcred-x", "vm-1")):
			with self.assertRaises(frappe.AuthenticationError):
				verify_bootstrap_token(other)

	def test_server_open_gates_the_handoff(self):
		# server:open is the console gate, distinct from server:view (which only lists).
		# A Developer carries it and can open; a Viewer sees servers but cannot open one.
		dev_team = self.make_team(self.developer, "Developer")
		link = self._open(self.developer, team=dev_team.name, gateway_url="http://localhost:3030")
		self.assertIn("/?sid=", link["url"])

		view_team = self.make_team(self.viewer, "Viewer")
		frappe.set_user(self.viewer)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_bench_link(team=view_team.name, gateway_url="http://localhost:3030")
		finally:
			frappe.set_user("Administrator")
