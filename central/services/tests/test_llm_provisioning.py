# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.services import provisioning
from central.services.api import dashboard, pilot
from central.services.drivers.grove import GroveDriver

_FAKE = {
	"gateway_url": "https://llm.frappe.cloud",
	"api_key": "gr_sk_testsecret",
	"provider_ref": "acme-example-com@svc.frappe.cloud",
}


def _ensure_llm_service():
	"""The LLM add-on's catalog entry. Operator-provisioned in prod (not seeded), so
	tests must stand it up before linking a Service Backend / Managed Service to it.
	Its Plan Category ("AI Tokens") is seeded on install by the billing taxonomy."""
	if not frappe.db.exists("Add-on Service", "llm"):
		frappe.get_doc(
			{
				"doctype": "Add-on Service",
				"service_key": "llm",
				"title": "LLM Hosting",
				"handler_key": "grove",
				"plan_category": "AI Tokens",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


class TestLLMProvisioning(IntegrationTestCase):
	def setUp(self):
		site = frappe.get_all("Site", fields=["name", "team"], limit=1)
		subscription = frappe.get_all("Subscription", pluck="name", limit=1)
		if not site or not subscription:
			self.skipTest("Needs at least one Site and Subscription on the site.")

		self.site, self.team = site[0].name, site[0].team

		_ensure_llm_service()
		# Frappe rolls the suite back only at class teardown, so wipe our own rows
		# between methods to avoid the composite-unique guard tripping on reuse.
		frappe.db.delete("Site Service Credential", {"site": self.site})
		for ms in frappe.get_all(
			"Managed Service", {"team": self.team, "add_on_service": "llm"}, pluck="name"
		):
			frappe.db.delete("Service API Key", {"managed_service": ms})
		frappe.db.delete("Managed Service", {"team": self.team, "add_on_service": "llm"})
		frappe.db.delete("Service Backend", {"service": "llm"})

		self.backend = frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": "llm",
				"base_url": "http://grove.localhost:8001",
				"control_api_key": "control-key",
				"control_api_secret": "control-secret",
				"is_active": 1,
			}
		).insert()

		self.managed = frappe.get_doc(
			{
				"doctype": "Managed Service",
				"team": self.team,
				"add_on_service": "llm",
				"subscription": subscription[0],
				"status": "Active",
			}
		).insert()

	def test_provision_site_builds_grove_call(self):
		with patch("central.services.drivers.grove.requests.post") as post:
			post.return_value.status_code = 200
			post.return_value.json.return_value = {
				"message": {"gateway_url": _FAKE["gateway_url"], "api_key": _FAKE["api_key"]}
			}
			result = GroveDriver().provision_site(self.backend, "acme.example.com", {})

		called_url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs.get("url")
		self.assertIn("grove.api.provision_key", called_url)
		self.assertEqual(result["gateway_url"], _FAKE["gateway_url"])
		self.assertEqual(result["api_key"], _FAKE["api_key"])
		self.assertEqual(result["provider_ref"], "acme-example-com@svc.frappe.cloud")

	def test_enable_site_stores_encrypted_credential(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			out = provisioning.enable_site(self.managed.name, self.site)

		self.assertEqual(out["status"], "Active")
		credential = frappe.get_doc("Site Service Credential", out["credential"])
		self.assertEqual(credential.gateway_url, _FAKE["gateway_url"])
		self.assertEqual(credential.get_password("api_key"), _FAKE["api_key"])

	def test_enable_site_is_idempotent(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			first = provisioning.enable_site(self.managed.name, self.site)
			second = provisioning.enable_site(self.managed.name, self.site)

		self.assertEqual(first["credential"], second["credential"])

	def test_enable_after_revoke_reuses_row(self):
		with (
			patch.object(GroveDriver, "provision_site", return_value=_FAKE),
			patch.object(GroveDriver, "revoke_site"),
		):
			first = provisioning.enable_site(self.managed.name, self.site)
			provisioning.disable_site(self.managed.name, self.site)
			again = provisioning.enable_site(self.managed.name, self.site)

		self.assertEqual(first["credential"], again["credential"])
		self.assertEqual(again["status"], "Active")

	def test_enable_requires_active_entitlement(self):
		# The bench can only enable once the team has activated the service — that's the
		# Central-console billing gate.
		frappe.db.set_value("Managed Service", self.managed.name, "status", "Draft")
		with self.assertRaises(frappe.ValidationError):
			provisioning.active_managed_service(self.team, "llm")

	def test_get_config_returns_delivered_config(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			provisioning.enable_site(self.managed.name, self.site)

		config = pilot.config_for_site(self.team, self.site, "llm")

		self.assertEqual(config["gateway_url"], _FAKE["gateway_url"])
		self.assertEqual(config["api_key"], _FAKE["api_key"])

	def test_get_config_rejects_a_team_without_the_credential(self):
		# Team-scoped by the credential lookup: another team resolves no credential, so
		# it can't read one — no cross-team leak, and no site-mirror dependency.
		with self.assertRaises(frappe.ValidationError):
			pilot.config_for_site("TEAM-not-owner", self.site, "llm")

	def test_generate_api_key_mints_and_stores_secret(self):
		with patch.object(GroveDriver, "provision_key", return_value=_FAKE):
			out = dashboard.generate_api_key(self.managed.name, "n8n prod")

		self.assertEqual(out["status"], "Active")
		self.assertEqual(out["api_key"], _FAKE["api_key"])
		key = frappe.get_doc("Service API Key", out["name"])
		self.assertEqual(key.label, "n8n prod")
		self.assertEqual(key.get_password("api_key"), _FAKE["api_key"])
		# list never leaks the secret
		listed = dashboard.list_api_keys(self.managed.name)
		self.assertEqual(listed[0]["name"], out["name"])
		self.assertNotIn("api_key", listed[0])

	def test_reveal_and_revoke_api_key(self):
		with patch.object(GroveDriver, "provision_key", return_value=_FAKE):
			out = dashboard.generate_api_key(self.managed.name, "app")

		revealed = dashboard.reveal_api_key(out["name"])
		self.assertEqual(revealed["api_key"], _FAKE["api_key"])

		with patch.object(GroveDriver, "revoke_site") as revoke:
			dashboard.revoke_api_key(out["name"])
		revoke.assert_called_once()
		self.assertEqual(frappe.db.get_value("Service API Key", out["name"], "status"), "Revoked")
		# a revoked key can't be revealed
		with self.assertRaises(frappe.ValidationError):
			dashboard.reveal_api_key(out["name"])

	def test_usage_reconciliation_includes_api_keys(self):
		from central.services import llm

		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			provisioning.enable_site(self.managed.name, self.site)
		with patch.object(
			GroveDriver, "provision_key", return_value={**_FAKE, "provider_ref": "key-abc@svc.frappe.cloud"}
		):
			dashboard.generate_api_key(self.managed.name, "app")

		emails = llm._team_credentials("llm").get(self.team, [])
		self.assertIn(_FAKE["provider_ref"], emails)  # the site key
		self.assertIn("key-abc@svc.frappe.cloud", emails)  # the api key

	def test_list_offers_marks_activated(self):
		offers = dashboard.list_offers(self.team)
		llm_offer = next(o for o in offers if o["name"] == "llm")
		self.assertEqual(llm_offer["managed_service"], self.managed.name)

	def test_activation_explains_how_to_get_access_when_the_plan_is_missing(self):
		# Title-agnostic: the service's display title is operator-set, so assert the
		# stable, actionable part of the message rather than the exact title.
		with patch.object(dashboard, "_resolve_subscription", return_value=None):
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"is not available in this team's plan. Ask your account administrator to add it",
			):
				dashboard.activate_service(self.team, "llm")

	def test_get_instance_returns_status_sites_models(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			provisioning.enable_site(self.managed.name, self.site)

		instance = dashboard.get_instance(self.managed.name)
		self.assertEqual(instance["status"], "Active")
		self.assertIn(self.site, instance["enabled_sites"])
		self.assertIsInstance(instance["models"], list)

	def test_reads_require_capability(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			dashboard.list_offers(self.team)


class TestLLMPolicyAndUsage(IntegrationTestCase):
	def setUp(self):
		from central.services import llm

		self.llm = llm
		_ensure_llm_service()
		frappe.db.delete("Service Backend", {"service": "llm"})
		frappe.db.delete("LLM Model", {"model_key": ["in", ["m-fast", "m-premium", "m-stale"]]})

		frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": "llm",
				"base_url": "http://grove.localhost:8001",
				"control_api_key": "k",
				"control_api_secret": "s",
				"is_active": 1,
			}
		).insert()

	def test_sync_models_upserts_and_unpublishes(self):
		frappe.get_doc(
			{"doctype": "LLM Model", "model_key": "m-stale", "tier": "Fast", "is_published": 1}
		).insert()

		catalog = [
			{"name": "m-fast", "display_name": "Fast"},
			{"name": "m-premium", "display_name": "Premium"},
		]
		with patch("central.services.drivers.grove.GroveDriver.list_models", return_value=catalog):
			count = self.llm.sync_models()

		self.assertEqual(count, 2)
		self.assertTrue(frappe.db.get_value("LLM Model", "m-fast", "is_published"))
		self.assertFalse(frappe.db.get_value("LLM Model", "m-stale", "is_published"))

	def test_resolve_options_gates_by_tier(self):
		frappe.get_doc(
			{"doctype": "LLM Model", "model_key": "m-fast", "tier": "Fast", "is_published": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "LLM Model", "model_key": "m-premium", "tier": "Premium", "is_published": 1}
		).insert()

		plans = frappe.get_all("Plan", pluck="name", limit=1)
		if not plans:
			self.skipTest("Needs at least one Plan.")
		plan = plans[0]
		frappe.db.delete("LLM Plan Tier", {"parent": plan})
		frappe.db.delete("LLM Plan Policy", {"plan": plan})
		frappe.get_doc(
			{"doctype": "LLM Plan Policy", "plan": plan, "allowed_tiers": [{"tier": "Fast"}]}
		).insert()

		options = self.llm.resolve_provision_options(plan)
		self.assertIn("m-fast", options["allowed_models"])
		self.assertNotIn("m-premium", options["allowed_models"])

	def test_resolve_options_denies_when_tier_has_no_models(self):
		frappe.db.delete("LLM Model", {"tier": "Premium"})
		plans = frappe.get_all("Plan", pluck="name", limit=1)
		if not plans:
			self.skipTest("Needs at least one Plan.")
		plan = plans[0]
		frappe.db.delete("LLM Plan Tier", {"parent": plan})
		frappe.db.delete("LLM Plan Policy", {"plan": plan})
		frappe.get_doc(
			{"doctype": "LLM Plan Policy", "plan": plan, "allowed_tiers": [{"tier": "Premium"}]}
		).insert()

		# A configured-but-empty policy must refuse, never fall through to unrestricted.
		with self.assertRaises(frappe.ValidationError):
			self.llm.resolve_provision_options(plan)

	def test_pull_usage_sums_and_reports(self):
		usage = {
			"users": ["x"],
			"month": "2026-07",
			"x@svc": {"billable_tokens": 100},
			"y@svc": {"billable_tokens": 50},
		}
		captured = {}

		def _fake_ingest(payload):
			captured.update(payload)
			return "rollup-1"

		with (
			patch("central.services.llm._team_credentials", return_value={"TEAM-X": ["x@svc", "y@svc"]}),
			patch("central.services.drivers.grove.GroveDriver.fetch_usage", return_value=usage),
			patch("central.billing.catalog.services.resolve_service_subject", return_value="SUBJ"),
			patch("central.billing.catalog.subscriptions.active_segment_for_resource", return_value=None),
			patch("central.billing.revenue.metering.ingest_rollup", side_effect=_fake_ingest),
		):
			result = self.llm.pull_usage()

		self.assertEqual(result["teams_reported"], 1)
		self.assertEqual(captured["quantity"], 150)

	def test_pull_usage_isolates_team_failures(self):
		def _usage(backend, emails):
			if emails == ["a@svc"]:
				raise ValueError("grove failed for team A")
			return {"b@svc": {"billable_tokens": 42}}

		with (
			patch(
				"central.services.llm._team_credentials",
				return_value={"TEAM-A": ["a@svc"], "TEAM-B": ["b@svc"]},
			),
			patch("central.services.drivers.grove.GroveDriver.fetch_usage", side_effect=_usage),
			patch("central.services.llm._report_tokens", return_value=True) as report,
			patch("frappe.log_error"),
		):
			result = self.llm.pull_usage()

		self.assertEqual(result["teams_reported"], 1)
		self.assertEqual(result["teams_failed"], 1)
		report.assert_called_once_with("TEAM-B", 42)


class TestBackendEnroll(IntegrationTestCase):
	def setUp(self):
		_ensure_llm_service()
		frappe.db.delete("Service Backend", {"service": "llm"})

	def test_register_backend_stores_minted_credential(self):
		from central.services.api import ops

		minted = {"api_key": "gr_key", "api_secret": "gr_sec", "user": "central-control@frappe.cloud"}
		with patch("central.services.drivers.grove.GroveDriver.enroll", return_value=minted):
			result = ops.register_backend("llm", "http://grove.localhost:8001", "bootstrap-xyz")

		self.assertEqual(result["is_active"], 1)
		backend = frappe.get_doc("Service Backend", result["backend"])
		self.assertEqual(backend.control_api_key, "gr_key")
		self.assertEqual(backend.get_password("control_api_secret"), "gr_sec")

	def test_enroll_pops_secret_from_form_dict(self):
		backend = frappe.get_doc(
			{"doctype": "Service Backend", "service": "llm", "base_url": "http://grove.localhost:8001"}
		).insert()

		frappe.local.form_dict = frappe._dict(bootstrap_secret="one-time-secret")
		minted = {"api_key": "gr_key", "api_secret": "gr_sec", "user": "central-control@frappe.cloud"}
		with patch("central.services.drivers.grove.GroveDriver.enroll", return_value=minted):
			backend.enroll()

		self.assertNotIn("bootstrap_secret", frappe.local.form_dict)
		self.assertEqual(backend.control_api_key, "gr_key")
		self.assertTrue(backend.is_active)
