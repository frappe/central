# Copyright (c) 2026, frappe and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.grove import GroveClient
from central.services import ai
from central.services.api import ai as api
from central.services.doctype.ai_settings import ai_settings

MINTED = {
	"name": "k1",
	"geography": "eu",
	"gateway_url": "https://eu.llm.frappe.cloud",
	"api_key": "gr_testsecret",
}
LIMITS = [{"metric": "requests", "window": "1m", "value": 20}]
LISTED = {
	"name": "k1",
	"title": "app",
	"status": "active",
	"creation": "2026-10-06 10:00:00",
	"revocable_at": "2026-10-06T10:30:00Z",
	"key_hash": "abc123",
	"masked": "gr_tes…cret",
	"geography": "eu",
	"gateway_url": "https://eu.llm.frappe.cloud",
	"cap": 5.0,
	"spent": 1.25,
	"limits": LIMITS,
}
MODELS = [{"name": "m", "dialects": ["openai"]}]
GEOGRAPHIES = [
	{"name": "eu", "label": "Europe", "endpoint": "https://eu.llm.frappe.cloud", "is_default": True}
]
EMPTY_USAGE = {
	"from_date": "2026-09-30",
	"to_date": "2026-09-30",
	"as_of": None,
	"model_summary": [],
	"daily_summary": [],
}


@contextmanager
def grove_replies(message):
	with patch("central.integrations.grove.requests.post") as post:
		post.return_value.status_code = 200
		post.return_value.json.return_value = {"message": message}
		yield post


def sent(post) -> tuple[str, dict]:
	return post.call_args.args[0].rsplit("/api/method/", 1)[1], post.call_args.kwargs["json"]


class TestGroveClientCalls(IntegrationTestCase):
	"""What the client puts on the wire. The argument names are Grove's `grove.api` signatures:
	Grove drops a name it does not know and rejects a wrong type."""

	def setUp(self):
		self.client = GroveClient("http://grove.localhost:8001", "control-key", "control-secret")

	def test_enroll_exchanges_the_bootstrap_secret_and_nothing_else(self):
		minted = {"api_key": "gr_key", "api_secret": "gr_sec"}
		with grove_replies(minted) as post:
			result = GroveClient.enroll("http://grove.localhost:8001", "bootstrap-xyz")

		self.assertEqual(
			sent(post),
			(
				"grove.api.create_control_client",
				{"email": f"central@{frappe.local.site}", "token": "bootstrap-xyz"},
			),
		)
		self.assertNotIn("headers", post.call_args.kwargs)
		self.assertEqual(result, minted)

	def test_a_team_is_registered_under_the_control_credential(self):
		with grove_replies({"team": "TEAM-1", "max_keys": 10}) as post:
			self.client.provision_team("TEAM-1", "owner@example.com", free=True)

		self.assertEqual(
			sent(post),
			("grove.api.provision_team", {"team": "TEAM-1", "email": "owner@example.com", "free": True}),
		)
		self.assertEqual(
			post.call_args.kwargs["headers"], {"Authorization": "token control-key:control-secret"}
		)

	def test_keys_are_minted_listed_capped_and_revoked_by_team_and_name(self):
		with grove_replies(MINTED) as post:
			self.client.provision_key("TEAM-1", "n8n prod", "eu", 5)
		self.assertEqual(
			sent(post),
			("grove.api.provision_key", {"team": "TEAM-1", "title": "n8n prod", "geography": "eu", "cap": 5}),
		)

		with grove_replies([LISTED]) as post:
			self.client.list_keys("TEAM-1")
		self.assertEqual(sent(post), ("grove.api.keys", {"team": "TEAM-1"}))

		with grove_replies(LISTED) as post:
			self.client.update_key("TEAM-1", "k1", 7.5)
		self.assertEqual(sent(post), ("grove.api.update_key", {"team": "TEAM-1", "key": "k1", "cap": 7.5}))

		with grove_replies("Revoked.") as post:
			self.client.revoke_key("TEAM-1", "k1")
		self.assertEqual(sent(post), ("grove.api.revoke_key", {"team": "TEAM-1", "key": "k1"}))

	def test_models_geographies_balance_usage_and_credit_name_the_team(self):
		calls = [
			(
				lambda: self.client.list_models("TEAM-1", "k1"),
				("grove.api.available_models", {"team": "TEAM-1", "key": "k1"}),
			),
			(lambda: self.client.list_geographies(), ("grove.api.geographies", {})),
			(lambda: self.client.get_balance("TEAM-1"), ("grove.api.balance", {"team": "TEAM-1"})),
			(
				lambda: self.client.get_usage(["TEAM-1"], period="Last 7 Days"),
				(
					"grove.api.usage",
					{"teams": ["TEAM-1"], "month": None, "period": "Last 7 Days", "key_hash": None},
				),
			),
			(
				lambda: self.client.add_credit("TEAM-1", 5, "ref-1"),
				("grove.api.add_credit", {"team": "TEAM-1", "amount": 5, "reference": "ref-1"}),
			),
		]
		for call, expected in calls:
			with grove_replies([]) as post:
				call()
			self.assertEqual(sent(post), expected)

	def test_a_grove_refusal_is_raised(self):
		with patch("central.integrations.grove.requests.post") as post:
			post.return_value.status_code = 403
			post.return_value.text = "Not permitted"
			with self.assertRaises(frappe.ValidationError):
				self.client.list_keys("TEAM-1")


class TestAI(IntegrationTestCase):
	def setUp(self):
		team = frappe.get_all(
			"Team", filters={"owner_user": ("is", "set")}, fields=["name", "owner_user"], limit=1
		)
		if not team:
			self.skipTest("Needs a Team with an owner on the site.")
		self.team, self.owner = team[0].name, team[0].owner_user

		settings = frappe.get_single("AI Settings")
		settings.update(
			{
				"base_url": "http://grove.localhost:8001",
				"control_api_key": "control-key",
				"control_api_secret": "control-secret",
			}
		)
		settings.save()
		frappe.db.delete("Team Service", {"add_on_service": "ai"})
		self.addCleanup(frappe.set_user, "Administrator")

	def enabled(self):
		with patch.object(GroveClient, "provision_team", return_value={"team": self.team, "max_keys": 10}):
			return ai.enable(self.team)

	def test_enabling_registers_the_team_as_free_at_its_alert_address(self):
		frappe.set_user(self.owner)
		with patch.object(
			GroveClient, "provision_team", return_value={"team": self.team, "max_keys": 10}
		) as provision_team:
			name = api.enable_ai(self.team)["name"]
			self.assertEqual(api.enable_ai(self.team)["name"], name)

		provision_team.assert_called_once_with(self.team, ai.get_alert_email(self.team), free=True)
		service = frappe.get_doc("Team Service", name)
		# Prepaid at Grove, and each key calls its own geography: no subscription, no region,
		# no endpoint on the row.
		self.assertEqual(
			(service.status, service.subscription, service.region, service.endpoint_url),
			("Active", None, None, None),
		)

	def test_the_alert_address_is_the_billing_contact_else_the_owner(self):
		if not frappe.db.exists("Billing Profile", self.team):
			frappe.get_doc({"doctype": "Billing Profile", "team": self.team}).insert(ignore_permissions=True)

		frappe.db.set_value("Billing Profile", self.team, "email", "billing@example.com")
		self.assertEqual(ai.get_alert_email(self.team), "billing@example.com")

		frappe.db.set_value("Billing Profile", self.team, "email", None)
		self.assertEqual(ai.get_alert_email(self.team), frappe.db.get_value("User", self.owner, "email"))

	def test_a_grove_refusal_leaves_ai_off(self):
		with patch.object(GroveClient, "provision_team", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				ai.enable(self.team)

		self.assertIsNone(ai.get_ai_service(self.team))

	def test_a_team_has_one_ai_service(self):
		self.enabled()
		duplicate = frappe.get_doc(
			{"doctype": "Team Service", "team": self.team, "add_on_service": "ai", "status": "Active"}
		)
		# Refused before Grove is dialled.
		with patch.object(GroveClient, "provision_team") as provision_team:
			with self.assertRaises(frappe.ValidationError):
				duplicate.insert()
		provision_team.assert_not_called()

	def test_storage_still_needs_a_region(self):
		storage = frappe.get_doc(
			{"doctype": "Team Service", "team": self.team, "add_on_service": "storage", "status": "Active"}
		)
		storage.subscription = "any"
		with self.assertRaises(frappe.MandatoryError):
			storage.validate()

	def test_ai_off_answers_with_nothing_and_refuses_the_rest(self):
		self.assertEqual(api.get_ai(self.team), {"enabled": False})
		with self.assertRaises(frappe.ValidationError):
			api.list_api_keys(self.team)

	def test_the_overview_carries_balance_this_months_usage_and_the_geographies(self):
		self.enabled()
		balance = {"balance": 12.5, "spent": 7.5, "unallocated": 2.0, "is_free_user": False}
		month = {**EMPTY_USAGE, self.team: {"requests": 6, "tokens": 900, "cost": 7.5}}
		with (
			patch.object(GroveClient, "get_balance", return_value=balance),
			patch.object(GroveClient, "get_usage", return_value=month) as get_usage,
			patch.object(GroveClient, "list_geographies", return_value=GEOGRAPHIES),
		):
			first = api.get_ai(self.team)

		self.assertEqual(first["balance"], balance)
		self.assertEqual(first["usage"]["tokens"], 900)
		self.assertEqual(first["usage"]["to_date"], EMPTY_USAGE["to_date"])
		self.assertEqual(first["geographies"], GEOGRAPHIES)
		self.assertEqual(get_usage.call_args.kwargs["period"], "This Month")

	def test_a_key_is_minted_in_a_geography_with_a_cap_and_its_secret_is_returned_once(self):
		self.enabled()
		with (
			patch.object(GroveClient, "provision_key", return_value=MINTED) as provision_key,
			patch.object(GroveClient, "list_models", return_value=MODELS) as list_models,
		):
			created = api.create_api_key(self.team, " app ", "eu", "5")
		provision_key.assert_called_once_with(self.team, "app", "eu", 5.0)
		list_models.assert_called_once_with(self.team, "k1")
		self.assertEqual(
			(created["api_key"], created["geography"], created["gateway_url"]),
			(MINTED["api_key"], "eu", MINTED["gateway_url"]),
		)
		self.assertEqual(created["models"][0]["name"], "m")

		with patch.object(GroveClient, "list_keys", return_value=[LISTED]):
			[listed] = api.list_api_keys(self.team)
		self.assertNotIn("key_hash", listed)
		self.assertEqual(
			(listed["masked"], listed["geography"], listed["cap"], listed["spent"], listed["limits"]),
			(LISTED["masked"], "eu", 5.0, 1.25, LIMITS),
		)
		# So the console can hold Revoke back instead of asking Grove and being refused.
		self.assertEqual(listed["revocable_at"], LISTED["revocable_at"])

		with patch.object(GroveClient, "update_key", return_value={**LISTED, "cap": 7.5}) as update_key:
			self.assertEqual(api.update_api_key(self.team, "k1", "7.5")["cap"], 7.5)
		update_key.assert_called_once_with(self.team, "k1", 7.5)

		with patch.object(GroveClient, "revoke_key") as revoke_key:
			api.revoke_api_key(self.team, "k1")
		revoke_key.assert_called_once_with(self.team, "k1")

	def test_a_keys_models_are_read_from_grove(self):
		self.enabled()
		with patch.object(GroveClient, "list_models", return_value=MODELS) as list_models:
			[model] = api.get_api_key_models(self.team, "k1")
		list_models.assert_called_once_with(self.team, "k1")
		self.assertEqual((model["name"], model["dialects"], model["input_modalities"]), ("m", ["openai"], []))

	def test_usage_of_one_key_sends_its_hash_and_an_unknown_key_is_refused(self):
		self.enabled()
		with (
			patch.object(GroveClient, "list_keys", return_value=[LISTED]),
			patch.object(GroveClient, "get_usage", return_value=EMPTY_USAGE) as get_usage,
		):
			report = api.get_usage(self.team, key="k1")
			self.assertEqual(get_usage.call_args.kwargs["key_hash"], "abc123")
			with self.assertRaises(frappe.DoesNotExistError):
				api.get_usage(self.team, key="someone-elses")

		self.assertEqual(report["totals"], {"requests": 0, "tokens": 0, "cost": 0})

	def test_usage_fills_the_quiet_days_for_every_model(self):
		self.enabled()
		usage = {
			"from_date": "2026-09-28",
			"to_date": "2026-09-29",
			"as_of": "2026-09-29T10:00:00Z",
			"model_summary": [{"model": "m-big", "requests": 2, "tokens": 300, "cost": 1.0}],
			"daily_summary": [
				{"day": "2026-09-29", "model": "m-big", "requests": 2, "tokens": 300, "cost": 1.0}
			],
			self.team: {"requests": 2, "tokens": 300, "cost": 1.0},
		}
		with patch.object(GroveClient, "get_usage", return_value=usage):
			report = api.get_usage(self.team, period="Last 30 Days")

		self.assertEqual(report["totals"], {"requests": 2, "tokens": 300, "cost": 1.0})
		self.assertEqual(
			report["daily"],
			[
				{"day": "2026-09-28", "model": "m-big", "requests": 0, "tokens": 0, "cost": 0},
				{"day": "2026-09-29", "model": "m-big", "requests": 2, "tokens": 300, "cost": 1.0},
			],
		)

	def test_only_an_operator_adds_credit(self):
		self.enabled()
		with patch.object(GroveClient, "add_credit", return_value={"balance": 5}) as add_credit:
			self.assertEqual(api.add_credit(self.team, 5, "ref-1"), {"balance": 5})
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				api.add_credit(self.team, 5, "ref-2")

		add_credit.assert_called_once_with(self.team, 5, "ref-1")

	def test_a_changed_alert_address_is_sent_to_grove_only_when_ai_is_on(self):
		team = frappe.get_doc("Team", self.team)
		with (
			patch.object(team, "has_value_changed", return_value=True),
			patch.object(frappe, "enqueue") as enqueue,
		):
			ai.on_alert_address_update(team)
			enqueue.assert_not_called()

			self.enabled()
			ai.on_alert_address_update(team)

		enqueue.assert_called_once_with(
			"central.services.ai.register_team", team=self.team, free=False, enqueue_after_commit=True
		)

	def test_a_team_save_reaches_the_alert_address_hook(self):
		with patch("central.services.ai.on_alert_address_update") as hook:
			frappe.get_doc("Team", self.team).save()

		hook.assert_called_once()

	def test_enroll_pops_the_secret_from_the_request_and_keeps_the_credential(self):
		minted = {"api_key": "gr_key", "api_secret": "gr_sec"}
		frappe.local.form_dict["bootstrap_secret"] = "bootstrap-xyz"
		with patch.object(GroveClient, "enroll", return_value=minted) as enroll:
			ai_settings.enroll()

		enroll.assert_called_once_with("http://grove.localhost:8001", "bootstrap-xyz")
		self.assertNotIn("bootstrap_secret", frappe.local.form_dict)
		settings = frappe.get_single("AI Settings")
		self.assertEqual(settings.control_api_key, "gr_key")
		self.assertEqual(settings.get_password("control_api_secret"), "gr_sec")
		with self.assertRaises(frappe.ValidationError):
			ai_settings.enroll()

	def test_rotation_asks_grove_for_a_new_secret_under_the_current_one(self):
		with patch.object(
			GroveClient, "rotate_control_key", return_value={"api_key": "k", "api_secret": "s2"}
		):
			ai_settings.rotate_credential()

		self.assertEqual(frappe.get_single("AI Settings").get_password("control_api_secret"), "s2")
