# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.oauth import disconnect, relay_token, start
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.oauth.oauth import PROVIDER
from central.integrations.oauth.meta import (
	GRAPH_URL,
	NO_PHONE_NUMBER,
	NO_WABA,
	PHONE_NUMBER_UNCLEAR,
	PIN_CHANGED,
	ROUTE,
	WABA_IN_USE,
)
from central.integrations.oauth.setup import ensure_email_oauth_providers
from central.permissions import meta_webhook_route_has_permission, meta_webhook_route_query_conditions
from central.tests import test_email_oauth

WHATSAPP_CALLBACK = "/api/method/whatsapp.whatsapp.oauth.callback"


class TestMetaSignIn(IntegrationTestCase):
	# the same team, server, site and Pilot credential as the email sign-in tests
	setUp = test_email_oauth.TestEmailOAuth.setUp
	enable_meta = test_email_oauth.TestEmailOAuth.enable_meta
	call_callback = test_email_oauth.TestEmailOAuth.call_callback

	def as_pilot(self, path: str, token: str | None = None):
		# no X-Pilot-Site header: Central takes the site from the sign-in
		set_request(method="POST", path=path, headers={"X-Pilot-Token": token or self.token})

	def sign_in(self, host: str | None = None) -> str:
		"""A team member signs in to Meta from `host` (this site by default); returns the WABA ID Meta will report."""
		self.enable_meta()
		self.as_pilot("/api/method/central.api.oauth.start")
		start(
			provider="meta",
			state="state-1",
			code_challenge="challenge-1",
			return_url=f"https://{host or self.site}{WHATSAPP_CALLBACK}",
		)
		self.call_callback(self.owner, state="state-1", code="meta-code")
		frappe.set_user("Administrator")
		return f"waba-{frappe.generate_hash(length=8)}"

	def relay(
		self,
		waba_id: str,
		token_reply: tuple[int, dict] | None = None,
		graph_reply=None,
	):
		"""relay_token for meta against a fake Meta; returns the result and the fake Graph API."""
		status, body = token_reply or (200, {"access_token": "meta-token", "token_type": "bearer"})
		post = self.enterContext(patch("central.integrations.oauth.oauth.requests.post"))
		post.return_value = Mock(ok=status < 400, json=Mock(return_value=body))
		graph = self.enterContext(patch("central.integrations.oauth.meta.requests.request"))
		graph.side_effect = graph_reply or fake_graph(waba_id)
		self.graph = graph  # kept for a test whose relay raises

		self.as_pilot("/api/method/central.api.oauth.relay_token")
		result = relay_token(
			provider="meta", grant_type="authorization_code", code="meta-code", code_verifier="verifier-1"
		)
		return result, post, graph

	def route_to(self, waba_id: str, site: str) -> None:
		frappe.get_doc(
			{"doctype": ROUTE, "waba_id": waba_id, "team": self.team, "server": self.server, "site": site}
		).insert()

	def add_domain(self, site: str | None) -> str:
		"""An active custom domain on this server, routed to `site`."""
		domain = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": f"shop-{frappe.generate_hash(length=6)}.example.com",
				"team": self.team,
				"region": frappe.db.get_value("Virtual Machine", self.server, "region"),
				"server": self.server,
				"site": site,
			}
		).insert(ignore_permissions=True)
		domain.db_set("status", "Active")
		return domain.name

	def other_site(self) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"other-{frappe.generate_hash(length=6)}.oauth.example.test",
					"team": self.team,
					"server": self.server,
				}
			)
			.insert()
			.name
		)

	def test_meta_is_seeded_disabled_with_the_embedded_signup_parameters(self):
		frappe.delete_doc(PROVIDER, "meta", force=True, ignore_missing=True)
		ensure_email_oauth_providers()
		meta = frappe.get_doc(PROVIDER, "meta")

		self.assertFalse(meta.enabled)
		self.assertEqual(set(meta.get_query_params()), {"config_id", "extras"})

	def test_meta_sign_in_link_has_the_embedded_signup_parameters_and_no_pkce(self):
		self.enable_meta()
		self.as_pilot("/api/method/central.api.oauth.start")

		link = start(
			provider="meta",
			state="s",
			code_challenge="challenge-1",
			return_url=f"https://{self.site}{WHATSAPP_CALLBACK}",
		)

		query = parse_qs(urlsplit(link["authorize_url"]).query)
		self.assertIn("config_id", query)
		self.assertIn("sessionInfoVersion", query["extras"][0])
		self.assertNotIn("code_challenge", query)

	def test_meta_sign_in_readies_the_account_and_routes_its_webhooks_to_the_site(self):
		waba_id = self.sign_in()

		result, post, graph = self.relay(waba_id)

		self.assertNotIn("code_verifier", post.call_args.kwargs["data"])
		self.assertEqual(
			(result["access_token"], result["app_id"], result["waba_id"], result["phone_id"]),
			("meta-token", "meta-app-id", waba_id, "phone-1"),
		)
		# the site names the account with the number and its business name
		self.assertEqual(
			(result["display_phone_number"], result["verified_name"]), ("+1 555-010-0001", "Acme Store")
		)
		self.assertRegex(result["pin"], r"^\d{6}$")
		self.assertGreaterEqual(len(result["webhook_secret"]), 32)

		calls = [(c.args[0], c.args[1].removeprefix(f"{GRAPH_URL}/")) for c in graph.call_args_list]
		self.assertEqual(
			calls,
			[
				("GET", "debug_token"),
				("GET", f"{waba_id}/phone_numbers"),
				("POST", f"{waba_id}/subscribed_apps"),
				("POST", "phone-1/register"),
			],
		)
		debug_token = graph.call_args_list[0].kwargs
		self.assertEqual(
			graph.call_args_list[1].kwargs["params"]["fields"],
			"id,platform_type,display_phone_number,verified_name",
		)
		self.assertEqual(debug_token["headers"]["Authorization"], "Bearer meta-app-id|meta-secret")
		# a number with no two-step PIN gets ours from register: its PIN is not set on its own
		self.assertEqual(graph.call_args_list[3].kwargs["json"]["pin"], result["pin"])

		route = frappe.get_doc(ROUTE, waba_id)
		self.assertEqual((route.team, route.server, route.site), (self.team, self.server, self.site))
		self.assertEqual(route.get_password("webhook_secret"), result["webhook_secret"])

	def test_meta_sign_in_picks_the_number_just_added_to_an_account_that_already_sends(self):
		waba_id = self.sign_in()
		numbers = [
			{"id": "old-live", "platform_type": "CLOUD_API"},
			{"id": "phone-1", "platform_type": "NOT_APPLICABLE"},
		]

		result, _post, graph = self.relay(waba_id, graph_reply=fake_graph(waba_id, phone_numbers=numbers))

		self.assertEqual(result["phone_id"], "phone-1")
		self.assertFalse([c for c in graph.call_args_list if "old-live" in c.args[1]])
		# Meta left out the number and name: the site gets None and names the account another way
		self.assertEqual((result["display_phone_number"], result["verified_name"]), (None, None))

	def test_meta_sign_in_refuses_an_account_where_the_new_number_is_not_clear(self):
		waba_id = self.sign_in()
		numbers = [
			{"id": "phone-1", "platform_type": "CLOUD_API"},
			{"id": "phone-2", "platform_type": "CLOUD_API"},
		]

		with self.assertRaisesRegex(frappe.ValidationError, f"^{PHONE_NUMBER_UNCLEAR}$"):
			self.relay(waba_id, graph_reply=fake_graph(waba_id, phone_numbers=numbers))

		self.assertEqual([c.args[0] for c in self.graph.call_args_list], ["GET", "GET"])
		self.assertFalse(frappe.db.exists(ROUTE, waba_id))

	def test_meta_sign_in_replaces_another_two_step_pin_only_when_register_needs_it(self):
		waba_id = self.sign_in()
		register = [pin_mismatch(), {"success": True}]

		result, _post, graph = self.relay(waba_id, graph_reply=fake_graph(waba_id, register=register))

		calls = [c.args[1].removeprefix(f"{GRAPH_URL}/") for c in graph.call_args_list[3:]]
		self.assertEqual(calls, ["phone-1/register", "phone-1", "phone-1/register"])
		self.assertEqual(graph.call_args_list[4].kwargs["json"], {"pin": result["pin"]})
		self.assertTrue(frappe.db.exists(ROUTE, waba_id))

	def test_meta_sign_in_keeps_the_pin_when_register_fails(self):
		waba_id = self.sign_in()
		limited = {"error": {"message": "rate limited", "code": 80008}}

		with self.assertRaisesRegex(frappe.ValidationError, "rate limited") as refused:
			self.relay(waba_id, graph_reply=fake_graph(waba_id, register=[limited]))

		self.assertNotIn(PIN_CHANGED, str(refused.exception))
		self.assertNotIn(("POST", f"{GRAPH_URL}/phone-1"), [c.args for c in self.graph.call_args_list])
		self.assertFalse(frappe.db.exists(ROUTE, waba_id))

	def test_meta_sign_in_says_the_pin_changed_when_register_fails_after_it(self):
		waba_id = self.sign_in()
		register = [pin_mismatch(), {"error": {"message": "rate limited", "code": 80008}}]

		with self.assertRaisesRegex(frappe.ValidationError, f"^{PIN_CHANGED}$"):
			self.relay(waba_id, graph_reply=fake_graph(waba_id, register=register))

		self.assertFalse(frappe.db.exists(ROUTE, waba_id))

	def test_meta_sign_in_again_replaces_the_webhook_secret(self):
		waba_id = self.sign_in()
		self.route_to(waba_id, self.site)

		result, _post, _graph = self.relay(waba_id)

		self.assertEqual(
			frappe.get_doc(ROUTE, waba_id).get_password("webhook_secret"), result["webhook_secret"]
		)

	def test_meta_sign_in_refuses_a_waba_routed_to_another_site(self):
		waba_id = self.sign_in()
		self.route_to(waba_id, self.other_site())

		with self.assertRaisesRegex(frappe.ValidationError, f"^{WABA_IN_USE}$"):
			self.relay(waba_id)

		# refused before Meta is changed for this site
		self.assertEqual([c.args[0] for c in self.graph.call_args_list], ["GET"])
		self.assertNotEqual(frappe.db.get_value(ROUTE, waba_id, "site"), self.site)

	def test_meta_sign_in_refuses_a_waba_another_site_routed_during_the_meta_steps(self):
		real_exists = frappe.db.exists
		# the second case misses the other route on the first look, as a sign-in that has not committed yet
		for misses_route in (False, True):
			waba_id = self.sign_in()
			other_site = self.other_site()
			with self.subTest(misses_route=misses_route):
				if misses_route:
					exists = self.enterContext(patch.object(frappe.db, "exists"))
					exists.side_effect = lambda dt, *a, **kw: (
						False if dt == ROUTE else real_exists(dt, *a, **kw)
					)
				reply = fake_graph(waba_id)

				def route_meanwhile(method, url, **kwargs):
					if url.endswith("/subscribed_apps"):
						self.route_to(waba_id, other_site)
					return reply(method, url, **kwargs)

				with self.assertRaisesRegex(frappe.ValidationError, f"^{WABA_IN_USE}$"):
					self.relay(waba_id, graph_reply=route_meanwhile)
				self.assertEqual(frappe.db.get_value(ROUTE, waba_id, "site"), other_site)

	def test_meta_sign_in_refuses_an_account_with_no_waba_or_no_number(self):
		for code, meta in ((NO_WABA, {"waba_scope": False}), (NO_PHONE_NUMBER, {"phone_numbers": []})):
			with self.subTest(code=code):
				waba_id = self.sign_in()
				with self.assertRaisesRegex(frappe.ValidationError, f"^{code}$"):
					self.relay(waba_id, graph_reply=fake_graph(waba_id, **meta))
				self.assertNotIn("POST", [c.args[0] for c in self.graph.call_args_list])

	def test_meta_refusal_codes_are_the_strings_the_site_matches(self):
		# the WhatsApp app on the site maps these exact strings to its messages
		self.assertEqual(
			(WABA_IN_USE, NO_WABA, NO_PHONE_NUMBER, PHONE_NUMBER_UNCLEAR, PIN_CHANGED),
			("waba_in_use", "no_waba", "no_phone_number", "phone_number_unclear", "pin_changed"),
		)

	def test_meta_sign_in_on_a_custom_domain_routes_to_its_site(self):
		waba_id = self.sign_in(host=self.add_domain(self.site))

		self.relay(waba_id)

		self.assertEqual(frappe.db.get_value(ROUTE, waba_id, "site"), self.site)

	def test_meta_sign_in_from_a_domain_with_no_site_is_refused_before_meta(self):
		waba_id = self.sign_in(host=self.add_domain(None))

		with self.assertRaises(frappe.PermissionError):
			self.relay(waba_id)

		self.assertFalse(self.graph.called)
		self.assertFalse(frappe.db.exists(ROUTE, waba_id))

	def test_meta_sign_in_from_a_domain_routed_to_another_servers_site_is_refused(self):
		other_server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-{frappe.generate_hash(length=6)}",
				"team": self.team,
				"region": frappe.db.get_value("Virtual Machine", self.server, "region"),
			}
		).insert()
		far_site = (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"far-{frappe.generate_hash(length=6)}.oauth.example.test",
					"team": self.team,
					"server": other_server.name,
				}
			)
			.insert()
			.name
		)
		waba_id = self.sign_in(host=self.add_domain(far_site))

		with self.assertRaises(frappe.PermissionError):
			self.relay(waba_id)

		self.assertFalse(self.graph.called)
		self.assertFalse(frappe.db.exists(ROUTE, waba_id))

	def test_meta_passes_on_an_expired_code_as_invalid_grant(self):
		waba_id = self.sign_in()
		expired = {
			"error": {"message": "expired", "type": "OAuthException", "code": 100, "error_subcode": 36007}
		}

		with self.assertRaisesRegex(frappe.ValidationError, "invalid_grant"):
			self.relay(waba_id, token_reply=(400, expired))

	def test_disconnect_drops_the_route_only_for_the_team_and_server_it_goes_to(self):
		waba_id = f"waba-{frappe.generate_hash(length=8)}"
		self.route_to(waba_id, self.site)
		other_server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-{frappe.generate_hash(length=6)}",
				"team": self.team,
				"region": frappe.db.get_value("Virtual Machine", self.server, "region"),
			}
		).insert()
		other_team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Other OAuth Team", "owner_user": self.owner}
		).insert()

		for team, server in ((self.team, other_server.name), (other_team.name, self.server)):
			token = PilotCredential.mint(
				team=team, pilot_credential_id=f"oauth-{frappe.generate_hash(length=6)}", server=server
			)
			self.as_pilot("/api/method/central.api.oauth.disconnect", token)
			with self.subTest(team=team, server=server), self.assertRaises(frappe.PermissionError):
				disconnect(waba_id=waba_id)
			self.assertTrue(frappe.db.exists(ROUTE, waba_id))

		self.as_pilot("/api/method/central.api.oauth.disconnect")
		disconnect(waba_id=waba_id)
		self.assertFalse(frappe.db.exists(ROUTE, waba_id))
		disconnect(waba_id=waba_id)  # a second call has nothing left to drop

	def test_only_a_system_manager_reaches_a_route(self):
		frappe.set_user(self.owner)
		self.assertEqual(meta_webhook_route_query_conditions(), "1 = 0")
		self.assertFalse(meta_webhook_route_has_permission(frappe._dict(team=self.team)))

		frappe.set_user("Administrator")
		self.assertEqual(meta_webhook_route_query_conditions(), "")
		self.assertTrue(meta_webhook_route_has_permission(frappe._dict(team=self.team)))


def pin_mismatch() -> dict:
	return {"error": {"message": "Two step verification PIN Mismatch", "code": 133005}}


def fake_graph(
	waba_id: str, phone_numbers: list | None = None, register: list | None = None, waba_scope: bool = True
):
	"""Meta's Graph API for one Embedded Signup: the WABA, its one new number, and success for each change.
	`register` lists the replies to register, one per call."""
	replies = {
		("GET", "debug_token"): {
			"data": {
				"app_id": "meta-app-id",
				"is_valid": True,
				"granular_scopes": [
					{"scope": "business_management"},
					{"scope": "whatsapp_business_management", "target_ids": [waba_id] if waba_scope else []},
					{"scope": "whatsapp_business_messaging", "target_ids": [waba_id]},
				],
			}
		},
		("GET", f"{waba_id}/phone_numbers"): {
			"data": [
				{
					"id": "phone-1",
					"platform_type": "NOT_APPLICABLE",
					"display_phone_number": "+1 555-010-0001",
					"verified_name": "Acme Store",
				}
			]
			if phone_numbers is None
			else phone_numbers
		},
		("POST", f"{waba_id}/subscribed_apps"): {"success": True},
		("POST", "phone-1"): {"success": True},
		("POST", "phone-1/register"): register or [{"success": True}],
	}

	def reply(method: str, url: str, **kwargs):
		body = replies[(method, url.removeprefix(f"{GRAPH_URL}/"))]
		if isinstance(body, list):
			body = body.pop(0) if len(body) > 1 else body[0]
		return Mock(ok="error" not in body, json=Mock(return_value=body))

	return reply
