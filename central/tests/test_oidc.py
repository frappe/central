import base64
import json
import time
from unittest.mock import patch

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from oauthlib.common import Request
from oauthlib.openid.connect.core.endpoints.pre_configured import Server

from central.api.jwks import jwks_document
from central.api.oidc import get_jwks
from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.oidc import DiscoveryPage, OIDCRequestValidator, get_openid_configuration
from central.tests.test_sso_keys import reset_signing_key

SERVER_URL = "https://central.example"
TEST_USER = "oidc-user@example.com"
REDIRECT_URI = "https://client.example/callback"


class TestOIDCProvider(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		reset_signing_key("oidc")
		CentralSSOSettings.instance().initialize_signing_key("oidc")

		for target in ("central.oidc.get_url", "frappe.oauth.get_server_url"):
			self.enterContext(patch(target, return_value=SERVER_URL))

		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc({"doctype": "User", "email": TEST_USER, "first_name": "OIDC"}).insert()

	def test_id_token_verifies_against_the_discovery_issuer_and_jwks(self) -> None:
		jwks = json.loads(get_jwks().get_data())

		claims = jwt.decode(
			self.issue_id_token(),
			jwt.PyJWK(jwks["keys"][0]).key,
			algorithms=["RS256"],
			audience="client",
			issuer=get_openid_configuration()["issuer"],
		)

		user = frappe.get_doc("User", TEST_USER)
		self.assertEqual(claims["sub"], user.get_social_login_userid("frappe"))
		self.assertEqual(claims["email"], TEST_USER)
		self.assertEqual(claims["nonce"], "nonce")

	def test_id_token_header_names_the_oidc_key(self) -> None:
		header = jwt.get_unverified_header(self.issue_id_token())

		self.assertEqual(header["alg"], "RS256")
		self.assertEqual(header["kid"], CentralSSOSettings.instance().oidc_key_id)

	def test_id_token_subject_falls_back_to_the_user_name(self) -> None:
		claims = jwt.decode(self.issue_id_token("Administrator"), options={"verify_signature": False})

		self.assertEqual(claims["sub"], "Administrator")

	def test_id_token_needs_the_operator_to_initialize_the_key(self) -> None:
		reset_signing_key("oidc")

		with self.assertRaises(frappe.ValidationError):
			self.issue_id_token()

	def test_the_atlas_and_pilot_jwks_does_not_publish_the_oidc_key(self) -> None:
		key_ids = {key["kid"] for key in jwks_document()["keys"]}

		self.assertNotIn(CentralSSOSettings.instance().oidc_key_id, key_ids)

	def test_authenticate_client_accepts_the_basic_secret(self) -> None:
		client = self.create_client()

		self.assertTrue(self.authenticate(f"{client.client_id}:{client.client_secret}"))

	def test_authenticate_client_rejects_a_wrong_basic_secret(self) -> None:
		client = self.create_client()

		self.assertFalse(self.authenticate(f"{client.client_id}:wrong"))

	def test_authenticate_client_accepts_the_post_secret(self) -> None:
		client = self.create_client()
		request = Request(
			f"{SERVER_URL}/token",
			body={"client_id": client.client_id, "client_secret": client.client_secret},
		)

		self.assertTrue(OIDCRequestValidator().authenticate_client(request))
		self.assertEqual(request.client_id, client.client_id)

	def test_authorization_code_scopes_come_from_the_code(self) -> None:
		code = self.create_code(self.create_client())

		scopes = OIDCRequestValidator().get_authorization_code_scopes(None, code.name, None, None)

		self.assertEqual(scopes, ["openid", "email"])

	def test_a_basic_auth_code_exchange_returns_an_id_token(self) -> None:
		client = self.create_client()
		code = self.create_code(client)
		basic = base64.b64encode(f"{client.client_id}:{client.client_secret}".encode()).decode()

		_headers, body, status = Server(OIDCRequestValidator()).create_token_response(
			f"{SERVER_URL}/token",
			"POST",
			{"grant_type": "authorization_code", "code": code.name, "redirect_uri": REDIRECT_URI},
			{"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
		)

		self.assertEqual(status, 200, body)
		self.assertIn("id_token", json.loads(body))

	def test_discovery_page_renders_only_its_path(self) -> None:
		self.assertTrue(DiscoveryPage("/oidc/.well-known/openid-configuration").can_render())
		self.assertFalse(DiscoveryPage("/.well-known/openid-configuration").can_render())

	def issue_id_token(self, user: str = TEST_USER) -> str:
		request = Request("https://client.example/callback")
		request.user, request.scopes, request.nonce = user, ["openid"], "nonce"
		id_token = {"aud": "client", "iat": int(time.time())}
		return OIDCRequestValidator().finalize_id_token(id_token, {"expires_in": 3600}, None, request)

	def create_code(self, client):
		return frappe.get_doc(
			{
				"doctype": "OAuth Authorization Code",
				"client": client.name,
				"user": TEST_USER,
				"scopes": "openid email",
				"authorization_code": frappe.generate_hash(),
				"redirect_uri_bound_to_authorization_code": REDIRECT_URI,
				"validity": "Valid",
			}
		).insert()

	def create_client(self):
		return frappe.get_doc(
			{
				"doctype": "OAuth Client",
				"app_name": "oidc-test",
				"redirect_uris": REDIRECT_URI,
				"default_redirect_uri": REDIRECT_URI,
				"scopes": "openid",
			}
		).insert()

	def authenticate(self, credentials: str) -> bool:
		basic = base64.b64encode(credentials.encode()).decode()
		request = Request(f"{SERVER_URL}/token", headers={"Authorization": f"Basic {basic}"})
		return OIDCRequestValidator().authenticate_client(request)
