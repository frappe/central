# Copyright (c) 2026, frappe and Contributors
# See license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.grove import GroveClient
from central.services import ai
from central.services.api import ai as api

MINTED = {"name": "k1", "gateway_url": "https://llm.frappe.cloud", "api_key": "gr_testsecret"}
LISTED = {
	"name": "k1",
	"title": "app",
	"status": "active",
	"creation": "2026-10-06 10:00:00",
	"key_hash": "abc123",
	"can_read_balance": 1,
	"masked": "gr_tes…cret",
}
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

	def test_a_user_is_registered_under_the_control_credential(self):
		with grove_replies({"geography": "Main"}) as post:
			self.client.provision_user("TEAM-1", "owner@example.com", free=True)

		self.assertEqual(
			sent(post),
			("grove.api.provision_user", {"user": "TEAM-1", "email": "owner@example.com", "free": True}),
		)
		self.assertEqual(
			post.call_args.kwargs["headers"], {"Authorization": "token control-key:control-secret"}
		)

	def test_keys_are_minted_listed_and_revoked_by_user_and_name(self):
		with grove_replies(MINTED) as post:
			self.client.provision_key("TEAM-1", "n8n prod")
		self.assertEqual(sent(post), ("grove.api.provision_key", {"user": "TEAM-1", "title": "n8n prod"}))

		with grove_replies([LISTED]) as post:
			self.client.list_keys("TEAM-1")
		self.assertEqual(sent(post), ("grove.api.keys", {"user": "TEAM-1"}))

		with grove_replies("Revoked.") as post:
			self.client.revoke_key("TEAM-1", "k1")
		self.assertEqual(sent(post), ("grove.api.revoke_key", {"user": "TEAM-1", "key": "k1"}))

	def test_models_limits_usage_and_credit_name_the_grove_user(self):
		calls = [
			(lambda: self.client.list_models("TEAM-1"), ("grove.api.available_models", {"user": "TEAM-1"})),
			(lambda: self.client.get_limits("TEAM-1"), ("grove.api.limits", {"user": "TEAM-1"})),
			(
				lambda: self.client.get_usage(["TEAM-1"], period="Last 7 Days"),
				(
					"grove.api.usage",
					{"users": ["TEAM-1"], "month": None, "period": "Last 7 Days", "key_hash": None},
				),
			),
			(
				lambda: self.client.add_credit("TEAM-1", 5, "ref-1"),
				("grove.api.add_credit", {"user": "TEAM-1", "amount": 5, "reference": "ref-1"}),
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
		with patch.object(GroveClient, "provision_user"):
			return ai.enable(self.team)

	def test_enabling_registers_the_team_as_a_free_grove_user_with_the_owners_email(self):
		frappe.set_user(self.owner)
		with patch.object(GroveClient, "provision_user") as provision_user:
			name = api.enable_ai(self.team)["name"]
			self.assertEqual(api.enable_ai(self.team)["name"], name)

		owner_email = frappe.db.get_value("User", self.owner, "email")
		provision_user.assert_called_once_with(self.team, owner_email, free=True)
		service = frappe.get_doc("Team Service", name)
		# Prepaid at Grove, and Grove picks the geography: no subscription, no region.
		self.assertEqual((service.status, service.subscription, service.region), ("Active", None, None))

	def test_a_grove_refusal_leaves_ai_off(self):
		with patch.object(GroveClient, "provision_user", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				ai.enable(self.team)

		self.assertIsNone(ai.get_ai_service(self.team))

	def test_a_team_has_one_ai_service(self):
		self.enabled()
		duplicate = frappe.get_doc(
			{"doctype": "Team Service", "team": self.team, "add_on_service": "ai", "status": "Active"}
		)
		with patch.object(GroveClient, "provision_user"), self.assertRaises(frappe.ValidationError):
			duplicate.insert()

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

	def test_a_key_secret_is_returned_once_and_listed_masked(self):
		self.enabled()
		with patch.object(GroveClient, "provision_key", return_value=MINTED) as provision_key:
			created = api.create_api_key(self.team, " app ")
		provision_key.assert_called_once_with(self.team, "app")
		self.assertEqual(created["api_key"], MINTED["api_key"])

		with patch.object(GroveClient, "list_keys", return_value=[LISTED]):
			[listed] = api.list_api_keys(self.team)
		self.assertNotIn("key_hash", listed)
		self.assertEqual(listed["masked"], LISTED["masked"])

		with patch.object(GroveClient, "revoke_key") as revoke_key:
			api.revoke_api_key(self.team, "k1")
		revoke_key.assert_called_once_with(self.team, "k1")

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

		self.assertEqual(report["totals"], {"requests": 0, "cost": 0})

	def test_usage_fills_the_quiet_days_for_every_model(self):
		self.enabled()
		usage = {
			"from_date": "2026-09-28",
			"to_date": "2026-09-29",
			"as_of": "2026-09-29T10:00:00Z",
			"model_summary": [{"model": "m-big", "requests": 2, "cost": 1.0}],
			"daily_summary": [{"day": "2026-09-29", "model": "m-big", "requests": 2, "cost": 1.0}],
			self.team: {"requests": 2, "cost": 1.0},
		}
		with patch.object(GroveClient, "get_usage", return_value=usage):
			report = api.get_usage(self.team, period="Last 30 Days")

		self.assertEqual(report["totals"], {"requests": 2, "cost": 1.0})
		self.assertEqual(
			report["daily"],
			[
				{"day": "2026-09-28", "model": "m-big", "requests": 0, "cost": 0},
				{"day": "2026-09-29", "model": "m-big", "requests": 2, "cost": 1.0},
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

	def test_a_new_owner_is_sent_to_grove_only_when_ai_is_on(self):
		team = frappe.get_doc("Team", self.team)
		with (
			patch.object(team, "has_value_changed", return_value=True),
			patch.object(frappe, "enqueue") as enqueue,
		):
			ai.on_team_update(team)
			enqueue.assert_not_called()

			self.enabled()
			ai.on_team_update(team)

		enqueue.assert_called_once_with(
			"central.services.ai.register_grove_user", team=self.team, free=False, enqueue_after_commit=True
		)

	def test_a_team_save_reaches_the_owner_change_hook(self):
		with patch("central.services.ai.on_team_update") as on_team_update:
			frappe.get_doc("Team", self.team).save()

		on_team_update.assert_called_once()

	def test_the_monthly_pull_reports_each_ai_teams_billable_tokens(self):
		self.enabled()
		usage = {self.team: {"billable_tokens": 1200}}
		with (
			patch.object(GroveClient, "get_usage", return_value=usage) as get_usage,
			patch.object(ai, "report_tokens", return_value=True) as report_tokens,
		):
			self.assertEqual(ai.pull_usage(), {"teams_reported": 1, "teams_failed": 0})

		get_usage.assert_called_once_with([self.team])
		report_tokens.assert_called_once_with(self.team, 1200)
