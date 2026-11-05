# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.email_oauth import callback, get_active_providers, relay_token, start
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.email_oauth.email_oauth import PROVIDER, PROVIDER_UNAVAILABLE
from central.integrations.email_oauth.setup import DEFAULT_PROVIDERS, ensure_email_oauth_providers
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

ZONE = "oauth.example.test"
SITE_CALLBACK = "/api/method/frappe.integrations.frappe_providers.email_oauth.callback"


class TestEmailOAuth(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		ensure_email_oauth_providers()
		self.microsoft = frappe.get_doc(PROVIDER, "microsoft")
		self.microsoft.update(
			{
				"client_id": "ms-client-id",
				"client_secret": "ms-secret",
				"enabled": 1,
				"scopes": [{"scope": scope} for scope in DEFAULT_PROVIDERS["microsoft"]["scopes"]],
			}
		).save()

		# fixtures roll back only after the whole class, so each test gets its own names
		suffix = frappe.generate_hash(length=6)
		self.owner = ensure_user("oauth.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "OAuth Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		region = ensure_atlas_instance("test-email-oauth", proxy_domain=ZONE)
		self.server = (
			frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": f"vm-{suffix}",
					"team": self.team,
					"region": region,
				}
			)
			.insert()
			.name
		)
		self.site = (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"acme-{suffix}.{ZONE}",
					"team": self.team,
					"server": self.server,
				}
			)
			.insert()
			.name
		)
		self.token = PilotCredential.mint(
			team=self.team, pilot_credential_id=f"oauth-{suffix}", server=self.server
		)

	def as_pilot(self, path: str):
		set_request(method="POST", path=path, headers={"X-Pilot-Token": self.token})

	def call_start(self, return_url: str, state: str = "state-1", **kwargs) -> dict:
		self.as_pilot("/api/method/central.api.email_oauth.start")
		return start(
			provider="microsoft", state=state, code_challenge="challenge-1", return_url=return_url, **kwargs
		)

	def call_callback(self, user: str, **params) -> frappe._dict:
		frappe.set_user(user)
		frappe.local.response = frappe._dict()
		callback(**params)
		return frappe.local.response

	# start

	def test_start_returns_microsofts_link_for_this_sign_in(self):
		result = self.call_start(f"https://{self.site}{SITE_CALLBACK}")

		query = parse_qs(urlsplit(result["authorize_url"]).query)
		self.assertEqual(result["client_id"], "ms-client-id")
		self.assertEqual(result["scopes"], DEFAULT_PROVIDERS["microsoft"]["scopes"])
		self.assertEqual(query["state"], ["state-1"])
		self.assertEqual(query["code_challenge"], ["challenge-1"])
		self.assertEqual(query["prompt"], ["select_account"])
		self.assertNotIn("login_hint", query)
		self.assertTrue(query["redirect_uri"][0].endswith("/api/method/central.api.email_oauth.callback"))
		note = frappe.cache.get_value("email_oauth:state-1")
		self.assertEqual((note["team"], note["server"]), (self.team, self.server))

	def test_start_with_a_login_hint_goes_to_that_account(self):
		result = self.call_start(f"https://{self.site}{SITE_CALLBACK}", login_hint="admin@example.com")

		query = parse_qs(urlsplit(result["authorize_url"]).query)
		self.assertEqual(query["login_hint"], ["admin@example.com"])
		self.assertNotIn("prompt", query)

	def test_start_refuses_a_return_url_off_this_server(self):
		for url in (
			f"https://evil.example.com{SITE_CALLBACK}",
			f"https://{self.site}/some/other/path",
			f"https://attacker@{self.site}{SITE_CALLBACK}",
		):
			with self.subTest(url=url), self.assertRaises(frappe.PermissionError):
				self.call_start(url)

	def test_start_refuses_a_provider_without_an_app(self):
		self.as_pilot("/api/method/central.api.email_oauth.start")
		for provider in ("google", "evil"):
			with (
				self.subTest(provider=provider),
				self.assertRaisesRegex(frappe.ValidationError, PROVIDER_UNAVAILABLE),
			):
				start(
					provider=provider,
					state="s",
					code_challenge="c",
					return_url=f"https://{self.site}{SITE_CALLBACK}",
				)

	def test_start_refuses_a_disabled_provider(self):
		self.microsoft.reload().update({"enabled": 0}).save()

		with self.assertRaisesRegex(frappe.ValidationError, PROVIDER_UNAVAILABLE):
			self.call_start(f"https://{self.site}{SITE_CALLBACK}")

	# get_active_providers

	def test_get_active_providers_lists_only_the_enabled_ones(self):
		frappe.db.set_value(PROVIDER, {"name": ("!=", "microsoft")}, "enabled", 0)
		self.as_pilot("/api/method/central.api.email_oauth.get_active_providers")
		self.assertEqual(get_active_providers(), ["microsoft"])

		self.microsoft.reload().update({"enabled": 0}).save()

		self.assertEqual(get_active_providers(), [])

	# Email OAuth Provider

	def test_provider_cannot_be_enabled_without_credentials(self):
		doc = frappe.get_doc(PROVIDER, "microsoft").update({"client_id": ""})

		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_seeding_leaves_an_edited_provider_alone(self):
		self.microsoft.reload().update({"scopes": [{"scope": "openid"}]}).save()

		ensure_email_oauth_providers()

		doc = frappe.get_doc(PROVIDER, "microsoft")
		self.assertEqual(doc.get_scopes(), ["openid"])
		self.assertEqual(doc.client_id, "ms-client-id")

	# every Pilot endpoint

	def test_endpoints_need_a_pilot_credential(self):
		calls = {
			"get_active_providers": get_active_providers,
			"start": lambda: start(
				provider="microsoft",
				state="s",
				code_challenge="c",
				return_url=f"https://{self.site}{SITE_CALLBACK}",
			),
			"relay_token": lambda: relay_token(
				provider="microsoft", grant_type="refresh_token", refresh_token="old"
			),
		}
		for name, call in calls.items():
			set_request(method="POST", path=f"/api/method/central.api.email_oauth.{name}")
			with self.subTest(endpoint=name), self.assertRaises(frappe.AuthenticationError):
				call()

	# callback

	def test_callback_gives_the_code_to_a_team_member(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")

		response = self.call_callback(self.owner, state="state-1", code="the-code")

		self.assertEqual(response.type, "redirect")
		self.assertEqual(parse_qs(urlsplit(response.location).query)["code"], ["the-code"])

	def test_callback_refuses_someone_outside_the_team(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")
		outsider = ensure_user("oauth.outsider@example.test")

		response = self.call_callback(outsider, state="state-1", code="the-code")

		query = parse_qs(urlsplit(response.location).query)
		self.assertEqual(query["error"], ["not_team_member"])
		self.assertNotIn("code", query)

	def test_callback_passes_on_a_cancelled_sign_in(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")

		response = self.call_callback(self.owner, state="state-1", error="access_denied")

		query = parse_qs(urlsplit(response.location).query)
		self.assertEqual(query["error"], ["access_denied"])
		self.assertNotIn("code", query)

	def test_callback_sends_a_logged_out_browser_to_log_in_and_back(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")

		response = self.call_callback("Guest", state="state-1", code="the-code")

		login = urlsplit(response.location)
		self.assertEqual(login.path, "/dashboard/login")
		back = urlsplit(parse_qs(login.query)["redirect-to"][0])
		self.assertEqual(back.path, "/api/method/central.api.email_oauth.callback")
		self.assertEqual(parse_qs(back.query), {"state": ["state-1"], "code": ["the-code"]})

		# back from the login as a team member: the code goes on to the site
		response = self.call_callback(self.owner, state="state-1", code="the-code")
		self.assertEqual(parse_qs(urlsplit(response.location).query)["code"], ["the-code"])

	def test_callback_sends_a_browser_to_log_in_only_once(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")
		self.call_callback("Guest", state="state-1", code="the-code")

		response = self.call_callback("Guest", state="state-1", code="the-code")

		self.assertEqual(parse_qs(urlsplit(response.location).query)["error"], ["not_team_member"])
		self.assertIsNone(frappe.cache.get_value("email_oauth:state-1"))

	def test_callback_passes_on_an_error_without_a_login(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")

		response = self.call_callback("Guest", state="state-1", error="access_denied")

		self.assertEqual(parse_qs(urlsplit(response.location).query)["error"], ["access_denied"])

	def test_callback_works_only_once(self):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")
		self.call_callback(self.owner, state="state-1", code="the-code")

		response = self.call_callback(self.owner, state="state-1", code="the-code")

		self.assertNotEqual(response.get("type"), "redirect")

	# relay_token

	def call_relay_token(self, microsoft_status: int, microsoft_body: dict, **params):
		post = self.enterContext(patch("central.integrations.email_oauth.email_oauth.requests.post"))
		post.return_value = Mock(ok=microsoft_status < 400, json=Mock(return_value=microsoft_body))
		self.as_pilot("/api/method/central.api.email_oauth.relay_token")
		return relay_token(provider="microsoft", **params), post

	def sign_in(self, code: str = "the-code"):
		self.call_start(f"https://{self.site}{SITE_CALLBACK}")
		self.call_callback(self.owner, state="state-1", code=code)
		frappe.set_user("Administrator")

	def test_relay_token_adds_the_secret_and_returns_microsofts_tokens(self):
		self.sign_in()

		token, post = self.call_relay_token(
			200,
			{"access_token": "at", "refresh_token": "rt"},
			grant_type="authorization_code",
			code="the-code",
			code_verifier="verifier-1",
		)

		self.assertEqual(token["access_token"], "at")
		sent = post.call_args.kwargs["data"]
		self.assertEqual((sent["client_id"], sent["client_secret"]), ("ms-client-id", "ms-secret"))
		self.assertTrue(sent["redirect_uri"].endswith("/api/method/central.api.email_oauth.callback"))

	def test_relay_token_swaps_a_code_only_for_the_server_whose_sign_in_got_it(self):
		self.sign_in()
		other_server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-other-{frappe.generate_hash(length=6)}",
				"team": self.team,
				"region": frappe.db.get_value("Virtual Machine", self.server, "region"),
			}
		).insert()
		self.token = PilotCredential.mint(
			team=self.team,
			pilot_credential_id=f"oauth-other-{frappe.generate_hash(length=6)}",
			server=other_server.name,
		)

		with self.assertRaises(frappe.PermissionError):
			self.call_relay_token(
				200,
				{"access_token": "at"},
				grant_type="authorization_code",
				code="the-code",
				code_verifier="verifier-1",
			)

	def test_relay_token_refuses_a_code_central_never_gave_out(self):
		with self.assertRaises(frappe.PermissionError):
			self.call_relay_token(
				200,
				{"access_token": "at"},
				grant_type="authorization_code",
				code="stolen-code",
				code_verifier="verifier-1",
			)

	def test_relay_token_passes_on_microsofts_error_code(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.call_relay_token(
				400, {"error": "invalid_grant"}, grant_type="refresh_token", refresh_token="old"
			)
		self.assertIn("invalid_grant", str(caught.exception))
