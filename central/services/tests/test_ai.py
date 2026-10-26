# Copyright (c) 2026, frappe and Contributors
# See license.txt

import json
from contextlib import contextmanager
from unittest.mock import PropertyMock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import complete_billing_profile, ensure_trust_tier_level
from central.integrations.grove import GroveClient, GroveUnavailable
from central.services import ai
from central.services.api import ai as api
from central.services.doctype.ai_settings import ai_settings
from central.tests.test_iam import ensure_user

MINTED = {
	"name": "k1",
	"geography": "eu",
	"gateway_url": "https://eu.llm.frappe.cloud",
	"api_key": "gr_testsecret",
}
LIMITS = [{"metric": "requests", "window": "1m", "value": 20}]
# Patch Frappe's send step: how it makes the HTTP call differs between Frappe versions.
SEND_WEBHOOK = "frappe.integrations.doctype.webhook.webhook.send_webhook_request"
LISTED = {
	"name": "k1",
	"title": "app",
	"status": "active",
	"creation": "2026-10-06 10:00:00",
	"revocable_at": "2026-10-06T10:30:00Z",
	"key_hash": "abc123",
	"masked": "gr_test…",
	"geography": "eu",
	"gateway_url": "https://eu.llm.frappe.cloud",
	"cap": 5.0,
	"limits": LIMITS,
}
MODELS = [
	{"name": "acme/m", "provider": "acme", "model_id": "m", "zero_data_retention": True, "dialects": ["openai"]}
]
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
				"grove.api.control.create_control_client",
				{"email": f"central@{frappe.local.site}", "token": "bootstrap-xyz"},
			),
		)
		self.assertNotIn("headers", post.call_args.kwargs)
		self.assertEqual(result, minted)

	def test_a_team_is_registered_under_the_control_credential(self):
		with grove_replies({"team": "TEAM-1", "max_keys": 0}) as post:
			self.client.provision_team("TEAM-1")

		self.assertEqual(
			sent(post),
			("grove.api.teams.provision_team", {"team": "TEAM-1"}),
		)
		self.assertEqual(
			post.call_args.kwargs["headers"], {"Authorization": "token control-key:control-secret"}
		)

	def test_keys_are_minted_listed_capped_and_revoked_by_team_and_name(self):
		with grove_replies(MINTED) as post:
			self.client.provision_key("TEAM-1", "n8n prod", "eu", 5)
		self.assertEqual(
			sent(post),
			(
				"grove.api.keys.provision_key",
				{"team": "TEAM-1", "title": "n8n prod", "geography": "eu", "cap": 5},
			),
		)

		with grove_replies({"spend": {}, "keys": [LISTED], "usage": EMPTY_USAGE}) as post:
			self.assertEqual(self.client.get_figures("TEAM-1")["keys"], [LISTED])
		self.assertEqual(sent(post), ("grove.api.usage.figures", {"team": "TEAM-1"}))

		with grove_replies([LISTED]) as post:
			self.client.update_caps("TEAM-1", {"k1": 7.5})
		self.assertEqual(sent(post), ("grove.api.keys.update_caps", {"team": "TEAM-1", "caps": {"k1": 7.5}}))

		with grove_replies("Revoked.") as post:
			self.client.revoke_key("TEAM-1", "k1")
		self.assertEqual(sent(post), ("grove.api.keys.revoke_key", {"team": "TEAM-1", "key": "k1"}))

	def test_models_geographies_spend_and_usage_name_the_team(self):
		calls = [
			(
				lambda: self.client.list_models("TEAM-1", "k1"),
				("grove.api.catalog.available_models", {"team": "TEAM-1", "key": "k1", "geography": None}),
			),
			(
				lambda: self.client.list_models(geography="eu"),
				("grove.api.catalog.available_models", {"team": None, "key": None, "geography": "eu"}),
			),
			(lambda: self.client.list_geographies(), ("grove.api.catalog.geographies", {})),
			(lambda: self.client.pull_usage("TEAM-1"), ("grove.api.usage.pull_usage", {"team": "TEAM-1"})),
			(
				lambda: self.client.get_usage(["TEAM-1"], period="Last 7 Days"),
				(
					"grove.api.usage.usage",
					{
						"teams": ["TEAM-1"],
						"month": None,
						"period": "Last 7 Days",
						"key_hash": None,
						"pulled_after": None,
						"pulled_until": None,
					},
				),
			),
			(
				lambda: self.client.update_team("TEAM-1", tier="Growth", observed_at="2026-10-15 10:00:00"),
				(
					"grove.api.teams.update_team",
					{
						"team": "TEAM-1",
						"suspended": None,
						"tier": "Growth",
						"observed_at": "2026-10-15 10:00:00",
						"log_payloads": None,
					},
				),
			),
			(
				lambda: self.client.rename_tier("Growth", "Grow"),
				("grove.api.teams.rename_tier", {"old": "Growth", "new": "Grow"}),
			),
		]
		for call, expected in calls:
			with grove_replies([]) as post:
				call()
			self.assertEqual(sent(post), expected)

	def test_a_grove_refusal_shows_a_tenant_no_grove_detail(self):
		marker = "grove-internal-" + frappe.generate_hash(length=8)
		frappe.set_user(ensure_user("grove.tenant@example.test"))
		self.addCleanup(frappe.set_user, "Administrator")

		with patch("central.integrations.grove.requests.post") as post:
			post.return_value.status_code = 500
			post.return_value.text = marker
			post.return_value.json.side_effect = ValueError
			with self.assertRaises(frappe.ValidationError) as refused:
				self.client.get_figures("TEAM-1")

		self.assertNotIn(marker, str(refused.exception))
		self.assertIn(
			marker, frappe.get_last_doc("Error Log", filters={"method": "Grove request failed"}).error
		)

	def test_a_grove_refusal_is_raised_with_groves_own_sentence(self):
		sentence = "This month's spend and caps would add up to 7.5 of a spend limit of 5."
		with patch("central.integrations.grove.requests.post") as post:
			post.return_value.status_code = 417
			post.return_value.json.return_value = {
				"exception": f"frappe.exceptions.ValidationError: {sentence}",
				"_server_messages": json.dumps([json.dumps({"message": sentence})]),
			}
			with self.assertRaises(frappe.ValidationError) as refused:
				self.client.get_figures("TEAM-1")
		self.assertNotIsInstance(refused.exception, GroveUnavailable, "a refusal is not an outage")
		self.assertEqual(str(refused.exception), sentence)

		# A body that is not Frappe's still names the status and what came back.
		with patch("central.integrations.grove.requests.post") as post:
			post.return_value.status_code = 403
			post.return_value.text = "Not permitted"
			post.return_value.json.side_effect = ValueError
			with self.assertRaises(frappe.ValidationError) as refused:
				self.client.get_figures("TEAM-1")
		self.assertIn("403", str(refused.exception))
		self.assertIn("Not permitted", str(refused.exception))

	def test_a_grove_that_is_down_or_in_maintenance_is_unavailable(self):
		with patch("central.integrations.grove.requests.post", side_effect=requests.ConnectionError):
			with self.assertRaises(GroveUnavailable):
				self.client.get_figures("TEAM-1")
		for status in (502, 503, 504):
			with patch("central.integrations.grove.requests.post") as post:
				post.return_value.status_code = status
				with self.assertRaises(GroveUnavailable, msg=status):
					self.client.get_figures("TEAM-1")


class TestAI(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.owner = ensure_user("ai.owner@example.test")
		team = frappe.get_doc({"doctype": "Team", "team_name": "AI Test Team", "owner_user": cls.owner})
		cls.team = team.insert(ignore_permissions=True).name

	def setUp(self):
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
		# Saving the settings creates the webhook; the rollback drops it but not the cached list.
		self.addCleanup(frappe.client_cache.delete_value, "webhooks")

	def enabled(self):
		with (
			patch.object(GroveClient, "provision_team", return_value={"team": self.team, "max_keys": 10}),
			patch.object(GroveClient, "update_team"),
		):
			return ai.enable(self.team)

	def test_enabling_registers_the_team_and_sends_its_limits(self):
		frappe.set_user(self.owner)
		with (
			patch.object(
				GroveClient, "provision_team", return_value={"team": self.team, "max_keys": 0}
			) as provision_team,
			patch.object(GroveClient, "update_team") as update_team,
		):
			name = api.enable_ai(self.team)["name"]
			self.assertEqual(api.enable_ai(self.team)["name"], name)

		provision_team.assert_called_once_with(self.team)
		# The tier's name goes with it, so the first key has room for a cap.
		update_team.assert_called_once_with(**ai.get_team_limits(self.team))
		service = frappe.get_doc("Team Service", name)
		# Postpaid, and each key calls its own geography: no subscription, no region, no
		# endpoint on the row.
		self.assertEqual(
			(service.status, service.subscription, service.region, service.endpoint_url),
			("Active", None, None, None),
		)

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

	def test_the_page_says_grove_is_unavailable_instead_of_failing(self):
		self.enabled()
		with patch.object(GroveClient, "get_figures", side_effect=GroveUnavailable):
			self.assertEqual(api.get_ai(self.team), {"enabled": True, "unavailable": True})

	def test_ai_off_answers_with_nothing_and_refuses_the_rest(self):
		self.assertEqual(api.get_ai(self.team), {"enabled": False})
		with self.assertRaises(frappe.ValidationError):
			api.list_api_keys(self.team)

	def test_the_overview_carries_spend_this_months_usage_and_the_geographies(self):
		self.enabled()
		spend = {
			"month_spent": 7.5,
			"capped": 20.0,
			"committed": 27.5,
			"spend_limit": 50.0,
			"max_keys": 10,
			"suspended": False,
		}
		month = {
			**EMPTY_USAGE,
			"from_date": "2026-09-29",
			"daily_summary": [
				{"day": "2026-09-30", "model": "m-big", "requests": 4, "tokens": 600, "cost": 5.0},
				{"day": "2026-09-30", "model": "m-small", "requests": 2, "tokens": 300, "cost": 2.5},
			],
			self.team: {"requests": 6, "tokens": 900, "cost": 7.5},
		}
		figures = {"spend": spend, "keys": [LISTED], "usage": month}
		with (
			patch.object(GroveClient, "get_figures", return_value=figures) as get_figures,
			patch.object(GroveClient, "list_geographies", return_value=GEOGRAPHIES),
		):
			first = api.get_ai(self.team)

		self.assertEqual(first["spend"], spend)
		self.assertEqual(first["usage"]["tokens"], 900)
		self.assertEqual(first["usage"]["to_date"], EMPTY_USAGE["to_date"])
		# One point a day, models summed, the quiet day at zero: the overview's sparklines.
		self.assertEqual(
			first["usage"]["daily"],
			[
				{"day": "2026-09-29", "requests": 0, "tokens": 0, "cost": 0},
				{"day": "2026-09-30", "requests": 6, "tokens": 900, "cost": 7.5},
			],
		)
		self.assertEqual(first["geographies"], GEOGRAPHIES)
		# One Grove read for spend and this month's usage: they are of one moment.
		get_figures.assert_called_once_with(self.team)

	def test_a_failed_models_read_does_not_cost_the_minted_secret(self):
		self.enabled()
		with (
			patch.object(GroveClient, "provision_key", return_value=MINTED),
			patch.object(GroveClient, "list_models", side_effect=GroveUnavailable),
		):
			created = api.create_api_key(self.team, "app", "eu", "5")
		self.assertEqual((created["api_key"], created["models"]), (MINTED["api_key"], []))
		self.assertNotIn("Grove", str(frappe.local.message_log), "the swallowed refusal leaves no message")

	def test_a_key_is_minted_in_a_geography_with_a_cap_and_its_secret_is_returned_once(self):
		self.enabled()
		with (
			patch.object(GroveClient, "provision_key", return_value=MINTED) as provision_key,
			patch.object(GroveClient, "list_models", return_value=MODELS) as list_models,
		):
			created = api.create_api_key(self.team, " app ", "eu", "5")
			# A cap is whole dollars: refused here, before Grove.
			with self.assertRaises(frappe.ValidationError):
				api.create_api_key(self.team, "app", "eu", "2.5")
		provision_key.assert_called_once_with(self.team, "app", "eu", 5)
		list_models.assert_called_once_with(self.team, "k1")
		self.assertEqual(
			(created["api_key"], created["geography"], created["gateway_url"]),
			(MINTED["api_key"], "eu", MINTED["gateway_url"]),
		)
		self.assertEqual(created["models"][0]["name"], "acme/m")

		with patch.object(GroveClient, "get_figures", return_value={"keys": [LISTED]}):
			[listed] = api.list_api_keys(self.team)
		self.assertNotIn("key_hash", listed)
		self.assertEqual(
			(listed["masked"], listed["geography"], listed["cap"], listed["limits"]),
			(LISTED["masked"], "eu", 5.0, LIMITS),
		)
		# So the console can hold Revoke back instead of asking Grove and being refused.
		self.assertEqual(listed["revocable_at"], LISTED["revocable_at"])

		with patch.object(GroveClient, "update_caps", return_value=[{**LISTED, "cap": 8}]) as update_caps:
			self.assertEqual(api.set_api_key_caps(self.team, {"k1": "8"})[0]["cap"], 8)
			with self.assertRaises(frappe.ValidationError):
				api.set_api_key_caps(self.team, {"k1": "7.5"})
		update_caps.assert_called_once_with(self.team, {"k1": 8})

		with patch.object(GroveClient, "revoke_key") as revoke_key:
			api.revoke_api_key(self.team, "k1")
		revoke_key.assert_called_once_with(self.team, "k1")

	def test_prompt_logging_is_set_at_grove_by_a_service_manager_only(self):
		self.enabled()
		outsider = ensure_user("grove.outsider@example.test")
		frappe.set_user(self.owner)
		with patch.object(GroveClient, "update_team", return_value={"log_payloads": 0}) as update_team:
			self.assertEqual(api.set_prompt_logging(enabled=False, team=self.team), {"log_payloads": False})
			frappe.set_user(outsider)
			with self.assertRaises(frappe.PermissionError):
				api.set_prompt_logging(enabled=True, team=self.team)
		update_team.assert_called_once_with(self.team, log_payloads=False)

	def test_refresh_usage_asks_grove_to_pull_the_team(self):
		self.enabled()
		with patch.object(GroveClient, "pull_usage", return_value={"sync": "PS-1"}) as pull_usage:
			self.assertEqual(api.pull_usage(self.team), {"sync": "PS-1"})
		pull_usage.assert_called_once_with(self.team)

	def test_a_geographys_models_are_read_from_grove(self):
		self.enabled()
		with patch.object(GroveClient, "list_models", return_value=MODELS) as list_models:
			[model] = api.get_models(self.team, "eu")
			api.get_models(self.team, "")
		self.assertEqual(
			[call.kwargs for call in list_models.call_args_list], [{"geography": "eu"}, {"geography": None}]
		)
		self.assertEqual(
			(model["name"], model["provider"], model["model_id"], model["zero_data_retention"]),
			("acme/m", "acme", "m", True),
		)

	def test_usage_of_one_key_sends_its_hash_and_an_unknown_key_is_refused(self):
		self.enabled()
		with (
			patch.object(GroveClient, "get_figures", return_value={"keys": [LISTED]}),
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

	def test_the_teams_limits_are_its_tiers_name_as_of_its_profile(self):
		complete_billing_profile(self.team)
		caps = frappe._dict(tier="Growth")
		with patch("central.billing.catalog.entitlements.get_team_caps", return_value=caps):
			before = ai.get_team_limits(self.team)
			modified = frappe.db.get_value("Billing Profile", self.team, "modified")
			self.assertEqual(before, {"team": self.team, "tier": "Growth", "observed_at": str(modified)})
			# The stamp is the profile's: Grove drops a body that is not newer than its last.
			frappe.get_doc("Billing Profile", self.team).save()
			self.assertGreater(ai.get_team_limits(self.team)["observed_at"], before["observed_at"])
			# Untiered: Grove's default tier.
			caps.tier = None
			self.assertEqual(ai.get_team_limits(self.team)["tier"], "")

	def test_a_renamed_tier_label_is_renamed_at_grove(self):
		def level(tier, before, changed=True):
			return frappe._dict(
				tier=tier,
				has_value_changed=lambda field: changed,
				get_doc_before_save=lambda: before and frappe._dict(tier=before),
			)

		with patch.object(GroveClient, "rename_tier") as rename_tier:
			ai.on_level_update(level("Grow", before="Growth"))
			rename_tier.assert_called_once_with("Growth", "Grow")
			rename_tier.reset_mock()
			# A new level, an unchanged label, and a Central not enrolled at Grove: nothing to rename.
			ai.on_level_update(level("Grow", before=None))
			ai.on_level_update(level("Growth", before="Growth", changed=False))
			with patch.object(
				ai_settings.AISettings, "is_enrolled", new_callable=PropertyMock, return_value=False
			):
				ai.on_level_update(level("Grow", before="Growth"))
			rename_tier.assert_not_called()

	def test_the_webhook_follows_the_url_and_the_credential(self):
		# setUp saved AI Settings enrolled: the Webhook is there, enabled and signed.
		webhook = frappe.get_doc("Webhook", ai_settings.WEBHOOK_NAME)
		self.assertEqual(
			(webhook.enabled, webhook.enable_security, webhook.request_url, webhook.webhook_doctype),
			(1, 1, "http://grove.localhost:8001/api/method/grove.api.teams.team_webhook", "Billing Profile"),
		)
		self.assertEqual(webhook.get_password("webhook_secret"), "control-secret")
		self.assertEqual(
			{row.key: row.value for row in webhook.webhook_headers},
			{"Content-Type": "application/json", ai_settings.CONTROL_KEY_HEADER: "control-key"},
		)
		with patch.object(
			GroveClient, "rotate_control_key", return_value={"api_key": "k2", "api_secret": "s2"}
		):
			ai_settings.rotate_credential()
		webhook.reload()
		self.assertEqual(
			(webhook.get_password("webhook_secret"), webhook.webhook_headers[1].value), ("s2", "k2")
		)
		# Not enrolled: kept, disabled, nothing signed.
		settings = frappe.get_single("AI Settings")
		settings.update({"control_api_key": None, "control_api_secret": None})
		settings.save()
		webhook.reload()
		self.assertEqual((webhook.enabled, webhook.enable_security), (0, 0))

	def test_a_changed_level_reaches_grove_by_the_webhook_and_a_quiet_save_does_not(self):
		from frappe.integrations.doctype.webhook import flush_webhook_execution_queue

		complete_billing_profile(self.team)
		frappe.db.set_value("Billing Profile", self.team, "trust_tier_level", None)
		logs = {"webhook": ai_settings.WEBHOOK_NAME, "reference_document": self.team}
		before = frappe.db.count("Webhook Request Log", logs)

		profile = frappe.get_doc("Billing Profile", self.team)
		profile.trust_tier_level = ensure_trust_tier_level("t-ai")
		profile.promotion_basis = "Raised for the AI webhook test."
		with patch(SEND_WEBHOOK) as send:
			send.return_value.status_code = 200
			send.return_value.text = "{}"
			profile.save()
			# What the after-commit hook does, without committing the test's transaction.
			flush_webhook_execution_queue()

		body = {"team": self.team, "tier": "t-ai", "observed_at": str(profile.modified)}
		send.assert_called_once()
		_method, url, headers, data, _timeout = send.call_args.args
		self.assertEqual(url, frappe.get_value("Webhook", logs["webhook"], "request_url"))
		self.assertEqual(data, body)
		self.assertEqual(headers[ai_settings.CONTROL_KEY_HEADER], "control-key")
		self.assertTrue(headers["X-Frappe-Webhook-Signature"])
		log = frappe.get_last_doc("Webhook Request Log", filters=logs)
		self.assertEqual((log.status, json.loads(log.data)), ("Delivered", body))

		# Anything but the level is Grove's business no more than before.
		profile.reload()
		profile.legal_name = "Quiet Co"
		with patch(SEND_WEBHOOK) as send:
			profile.save()
			flush_webhook_execution_queue()
		send.assert_not_called()
		self.assertEqual(frappe.db.count("Webhook Request Log", logs), before + 1)

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
