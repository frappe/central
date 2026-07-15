# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.services.api import dashboard, pilot
from central.services.drivers.grove import GroveDriver

_FAKE = {
	"gateway_url": "https://llm.frappe.cloud",
	"api_key": "gr_sk_testsecret",
	"provider_ref": "acme-example-com@svc.frappe.cloud",
}


class TestLLMProvisioning(IntegrationTestCase):
	def setUp(self):
		site = frappe.get_all("Site", fields=["name", "team"], limit=1)
		subscription = frappe.get_all("Subscription", pluck="name", limit=1)
		if not site or not subscription:
			self.skipTest("Needs at least one Site and Subscription on the site.")

		self.site, self.team = site[0].name, site[0].team

		# Frappe rolls the suite back only at class teardown, so wipe our own rows
		# between methods to avoid the composite-unique guard tripping on reuse.
		frappe.db.delete("Site Service Credential", {"site": self.site})
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
			post.return_value.json.return_value = {"message": {"gateway_url": _FAKE["gateway_url"], "api_key": _FAKE["api_key"]}}
			result = GroveDriver().provision_site(self.backend, "acme.example.com", {})

		called_url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs.get("url")
		self.assertIn("grove.api.provision_key", called_url)
		self.assertEqual(result["gateway_url"], _FAKE["gateway_url"])
		self.assertEqual(result["api_key"], _FAKE["api_key"])
		self.assertEqual(result["provider_ref"], "acme-example-com@svc.frappe.cloud")

	def test_enable_site_stores_encrypted_credential(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			out = dashboard.enable_site(self.managed.name, self.site)

		self.assertEqual(out["status"], "Active")
		credential = frappe.get_doc("Site Service Credential", out["credential"])
		self.assertEqual(credential.gateway_url, _FAKE["gateway_url"])
		self.assertEqual(credential.get_password("api_key"), _FAKE["api_key"])

	def test_enable_site_is_idempotent(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			first = dashboard.enable_site(self.managed.name, self.site)
			second = dashboard.enable_site(self.managed.name, self.site)

		self.assertEqual(first["credential"], second["credential"])

	def test_enable_after_revoke_reuses_row(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE), patch.object(GroveDriver, "revoke_site"):
			first = dashboard.enable_site(self.managed.name, self.site)
			dashboard.disable_site(self.managed.name, self.site)
			again = dashboard.enable_site(self.managed.name, self.site)

		self.assertEqual(first["credential"], again["credential"])
		self.assertEqual(again["status"], "Active")

	def test_get_config_returns_delivered_config(self):
		with patch.object(GroveDriver, "provision_site", return_value=_FAKE):
			dashboard.enable_site(self.managed.name, self.site)

		config = pilot.config_for_site(self.team, self.site, "llm")

		self.assertEqual(config["gateway_url"], _FAKE["gateway_url"])
		self.assertEqual(config["api_key"], _FAKE["api_key"])

	def test_get_config_rejects_foreign_team(self):
		with self.assertRaises(frappe.PermissionError):
			pilot.config_for_site("TEAM-not-owner", self.site, "llm")


class TestLLMPolicyAndUsage(IntegrationTestCase):
	def setUp(self):
		from central.services import llm

		self.llm = llm
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

		catalog = [{"name": "m-fast", "display_name": "Fast"}, {"name": "m-premium", "display_name": "Premium"}]
		with patch("central.services.drivers.grove.GroveDriver.list_models", return_value=catalog):
			count = self.llm.sync_models()

		self.assertEqual(count, 2)
		self.assertTrue(frappe.db.get_value("LLM Model", "m-fast", "is_published"))
		self.assertFalse(frappe.db.get_value("LLM Model", "m-stale", "is_published"))

	def test_resolve_options_gates_by_tier(self):
		frappe.get_doc({"doctype": "LLM Model", "model_key": "m-fast", "tier": "Fast", "is_published": 1}).insert()
		frappe.get_doc({"doctype": "LLM Model", "model_key": "m-premium", "tier": "Premium", "is_published": 1}).insert()

		plan = frappe.get_all("Plan", pluck="name", limit=1)[0]
		frappe.db.delete("LLM Plan Policy", {"plan": plan})
		frappe.get_doc(
			{"doctype": "LLM Plan Policy", "plan": plan, "allowed_tiers": [{"tier": "Fast"}]}
		).insert()

		options = self.llm.resolve_provision_options(plan)
		self.assertIn("m-fast", options["allowed_models"])
		self.assertNotIn("m-premium", options["allowed_models"])

	def test_pull_usage_sums_and_reports(self):
		usage = {"users": ["x"], "month": "2026-07", "x@svc": {"billable_tokens": 100}, "y@svc": {"billable_tokens": 50}}
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


class TestBackendEnroll(IntegrationTestCase):
	def setUp(self):
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
