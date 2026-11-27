import frappe
from frappe.auth import validate_auth
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, set_request
from frappe.utils.password import get_decrypted_password

from central.api.identity import create_api_key, list_api_keys, revoke_api_key
from central.api.models.teams import APIKeyRow
from central.api.support import get_ticket_options
from central.iam import (
	can,
	clear_grants_cache,
	get_user_team_names,
	is_active_team_member,
	user_has_operator_bypass,
)
from central.tests.test_iam import ensure_user


class TestAPIKeys(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.user = ensure_user("keys.developer@example.test")
		cls.viewer = ensure_user("keys.viewer@example.test")
		cls.owner = ensure_user("keys.owner@example.test")
		cls.team = cls.make_team("Keys A", {cls.user: "Developer", cls.viewer: "Viewer"})
		cls.other_team = cls.make_team("Keys B", {cls.user: "Developer"})

	@classmethod
	def make_team(cls, team_name: str, members: dict[str, str]) -> str:
		rows = [{"user": cls.owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in members.items()]
		team = {"doctype": "Team", "team_name": team_name, "owner_user": cls.owner, "members": rows}
		return frappe.get_doc(team).insert().name

	def setUp(self):
		self.request = getattr(frappe.local, "request", None)
		self.login_manager = getattr(frappe.local, "login_manager", None)
		frappe.set_user(self.user)

	def tearDown(self):
		frappe.local.api_key = None
		frappe.local.request = self.request
		frappe.local.login_manager = self.login_manager
		frappe.set_user("Administrator")

	def create(self, scopes: dict[str, str], team: str | None = None) -> str:
		return create_api_key(team or self.team, "deploy bot", 30, scopes)["token"]

	def sign_in(self, token: str, path: str = "/api/method/central.api.servers.registry", **headers):
		"""Authenticate the way a real request does, through Frappe and then the Central hook."""
		frappe.set_user("Guest")
		frappe.local.login_manager = frappe._dict(user="Guest")
		headers = {"Authorization": f"token {token}", "Frappe-Authorization-Source": "API Key", **headers}
		set_request(path=path, headers={key: value for key, value in headers.items() if value})
		# Tests share one request cache; a real request starts with an empty one.
		clear_grants_cache()
		validate_auth()

	def test_a_key_acts_only_on_its_team_and_scopes(self):
		self.sign_in(self.create({"Servers": "Read"}))

		self.assertEqual(frappe.session.user, self.user)
		self.assertTrue(can(self.user, self.team, "server:view"))
		self.assertFalse(can(self.user, self.team, "server:power"))
		self.assertFalse(can(self.user, self.other_team, "server:view"))
		self.assertFalse(is_active_team_member(self.user, self.other_team))
		self.assertEqual(get_user_team_names(self.user), [self.team])

	def test_a_key_request_the_hook_missed_gets_no_rights(self):
		self.sign_in(self.create({"Servers": "Read"}))
		frappe.local.api_key = None

		with self.assertRaises(frappe.AuthenticationError):
			can(self.user, self.team, "server:view")

	def test_a_key_never_does_more_than_the_users_role(self):
		frappe.set_user(self.viewer)
		self.sign_in(self.create({"Servers": "Write"}))

		self.assertTrue(can(self.viewer, self.team, "server:view"))
		self.assertFalse(can(self.viewer, self.team, "server:power"))

	def test_a_key_of_an_operator_has_no_operator_bypass(self):
		frappe.get_doc("User", self.user).add_roles("System Manager")
		self.addCleanup(lambda: frappe.get_doc("User", self.user).remove_roles("System Manager"))
		self.sign_in(self.create({"Servers": "Read"}))

		self.assertFalse(user_has_operator_bypass(self.user))
		self.assertFalse(can(self.user, self.other_team, "server:view"))

	def test_a_key_without_support_is_refused_on_a_suspended_team(self):
		self.sign_in(self.create({"Servers": "Read"}))
		frappe.db.set_value("Team", self.team, "status", "Suspended")
		self.addCleanup(frappe.db.set_value, "Team", self.team, "status", "Active")

		with self.assertRaises(frappe.PermissionError):
			get_ticket_options(self.team)

	def test_an_expired_or_disabled_key_is_refused(self):
		token = self.create({"Servers": "Read"})
		name = frappe.db.get_value("API Key", {"api_key": token.split(":")[0]})

		frappe.db.set_value("API Key", name, "expires_at", add_to_date(now_datetime(), minutes=-1))
		with self.assertRaises(frappe.AuthenticationError):
			self.sign_in(token)

		frappe.db.set_value("API Key", name, "enabled", 0)
		with self.assertRaises(frappe.AuthenticationError):
			self.sign_in(token)

	def test_a_key_reaches_only_the_listed_methods(self):
		token = self.create({"Servers": "Write"})
		self.sign_in(token, "/api/v2/method/central.api.servers.registry")

		for path in (
			"/api/method/central.api.identity.create_api_key",
			"/api/method/central.api.teams.invite_team_member",
			"/api/resource/User",
			"/api/method/frappe.client.get_list",
		):
			with self.subTest(path=path), self.assertRaises(frappe.PermissionError):
				self.sign_in(token, path)

	def test_the_secret_is_shown_once(self):
		token = self.create({"Servers": "Read", "Support": "Write"})
		api_key, secret = token.split(":")
		name = frappe.db.get_value("API Key", {"api_key": api_key})

		[key] = [key for key in list_api_keys()["keys"] if key.name == name]

		self.assertEqual(get_decrypted_password("API Key", name, "api_secret"), secret)
		self.assertEqual(set(key), set(APIKeyRow.__annotations__))
		self.assertIs(key.enabled, True)
		self.assertEqual(key.key_prefix, api_key[:8])
		self.assertNotIn("api_key", key)
		self.assertNotIn("api_secret", key)
		self.assertEqual(key.scopes, {"Servers": "Read", "Support": "Write"})

	def test_a_user_cannot_see_or_revoke_another_users_key(self):
		token = self.create({"Servers": "Read"})
		name = frappe.db.get_value("API Key", {"api_key": token.split(":")[0]})

		frappe.set_user(self.viewer)
		self.assertNotIn(name, [key.name for key in list_api_keys()["keys"]])
		with self.assertRaises(frappe.PermissionError):
			revoke_api_key(name)

		frappe.set_user(self.user)
		revoke_api_key(name)
		self.assertFalse(frappe.db.exists("API Key", name))

	def test_a_key_needs_a_team_of_the_user_and_known_levels(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.ValidationError):
			self.create({"Servers": "Read"}, team=self.other_team)

		for scopes in ({}, {"Support": "Read"}):
			with self.subTest(scopes=scopes), self.assertRaises(frappe.ValidationError):
				self.create(scopes)

	def test_an_expiry_past_the_limit_is_refused_on_every_path(self):
		key = frappe.get_doc(
			{
				"doctype": "API Key",
				"title": "forever",
				"user": self.user,
				"team": self.team,
				"expires_at": add_to_date(now_datetime(), days=3650),
				"scopes": [{"category": "Servers", "access": "Read"}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			key.insert()

	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		for method in (list_api_keys, create_api_key, revoke_api_key):
			with self.subTest(method=method.__name__), self.assertRaises(frappe.PermissionError):
				frappe.is_whitelisted(method)
