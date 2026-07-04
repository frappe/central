# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Consumer-service metered billing (ADR 0015): per-family settlement + reporting
mode, synthesized team-level subjects, dual-mode usage ingestion, and the
pilot-authenticated service API."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.tests.utils import complete_billing_profile, ensure_team, make_metered_plan


def _ensure_resource_type(name: str) -> str:
	"""A metered Plan's include links a Resource Type; ensure one exists for the test."""
	if not frappe.db.exists("Resource Type", name):
		frappe.get_doc({"doctype": "Resource Type", "resource_type_name": name}).insert(
			ignore_permissions=True
		)
	return name


def _make_metered_family(
	category, resource_type, plan, reporting_mode="Authoritative",
	settlement_mode="Postpaid Overage", allowance=0, rate=0.5,
):
	"""A metered single-resource Plan under a dedicated Plan Category carrying explicit
	reporting + settlement modes and an included allowance — so a test can exercise
	incremental accumulation / prepaid draw-down without mutating a shared category.
	Returns the plan name."""
	from central.billing.catalog.pricing import set_catalog_rates
	from central.billing.tests.utils import _ensure_rate_instances

	_ensure_resource_type(resource_type)
	for old in frappe.get_all("Plan", {"category": category}, pluck="name"):
		frappe.delete_doc("Plan", old, force=True)
	if frappe.db.exists("Plan Category", category):
		frappe.delete_doc("Plan Category", category, force=True)
	frappe.get_doc(
		{
			"doctype": "Plan Category", "category_name": category, "billing_type": "Metered",
			"pricing_mode": "Grandfathered", "reporting_mode": reporting_mode,
			"settlement_mode": settlement_mode,
		}
	).insert(ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": "Plan", "title": plan, "category": category, "billing_cycle": "Monthly",
			"is_active": 1,
			"includes": [{"resource_type": resource_type, "quantity": allowance, "unit": "unit"}],
		}
	)
	doc.name = plan
	doc.flags.name_set = True
	doc.insert(ignore_permissions=True)
	rates = [{"cluster": "", "currency": "INR", "rate": rate}]
	_ensure_rate_instances(rates)
	set_catalog_rates("Plan", doc.name, rates)
	return doc.name


class TestPlanCategoryModes(IntegrationTestCase):
	"""settlement_mode / reporting_mode are per-family properties, blank resolving to
	the built default; both are meaningless on a Fixed family (ADR 0015)."""

	def _category(self, name, billing_type="Metered", **kwargs):
		if frappe.db.exists("Plan Category", name):
			frappe.delete_doc("Plan Category", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "Plan Category", "category_name": name, "billing_type": billing_type, **kwargs}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_blank_modes_resolve_to_built_defaults(self):
		cat = self._category("SM Metered Blank")
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")

	def test_explicit_modes_are_honoured(self):
		cat = self._category(
			"SM Prepaid Incremental",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		self.assertEqual(cat.effective_settlement_mode, "Prepaid Pack")
		self.assertEqual(cat.effective_reporting_mode, "Incremental")

	def test_modes_cleared_on_fixed_family(self):
		cat = self._category(
			"SM Fixed Bundle",
			billing_type="Fixed",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		# A bundle has no metered reporting — the controller blanks both on validate.
		self.assertFalse(cat.settlement_mode)
		self.assertFalse(cat.reporting_mode)
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")


class TestServiceSubjectProvisioning(IntegrationTestCase):
	"""A team-level service is subscribed with a synthesized subject and no Asset
	(ADR 0013): the segment opens inline and metering resolves it like any resource."""

	TEAM = "svc-team-a"

	def setUp(self):
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="INR")
		frappe.db.delete("Subscription", {"team": self.TEAM})
		_ensure_resource_type("PDF Render")
		self.plan = make_metered_plan("Svc PDF Render", resource_type="PDF Render", unit="doc")

	def test_provision_synthesizes_subject_and_opens_segment(self):
		res = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")

		self.assertTrue(res["service_subject"].startswith("svc-"))
		self.assertFalse(res["reused"])
		self.assertEqual(res["currency"], "INR")

		sub = frappe.get_doc("Subscription", res["subscription"])
		self.assertEqual(sub.service_subject, res["service_subject"])
		self.assertFalse(sub.asset_id)  # no VM Asset for a team-level service
		self.assertEqual(sub.cluster, "mumbai")

		# Metering resolves the subject off the ledger, just like a VM resource.
		seg = subscriptions.active_segment_for_resource(res["service_subject"])
		self.assertIsNotNone(seg)
		self.assertEqual(seg.team, self.TEAM)
		self.assertEqual(seg.cluster, "mumbai")
		self.assertEqual(seg.currency, "INR")

	def test_reprovision_same_service_is_idempotent(self):
		first = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")
		second = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")

		self.assertEqual(first["service_subject"], second["service_subject"])
		self.assertEqual(first["subscription"], second["subscription"])
		self.assertTrue(second["reused"])
		self.assertEqual(
			frappe.db.count("Subscription", {"service_subject": first["service_subject"]}), 1
		)

	def test_different_cluster_is_a_distinct_subject(self):
		mumbai = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")
		blr = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="blr")
		self.assertNotEqual(mumbai["service_subject"], blr["service_subject"])

	def test_server_plan_rejected_as_service(self):
		from central.billing.tests.utils import make_plan

		server_plan = make_plan("Svc Server Plan", rates=[{"cluster": "", "currency": "INR", "rate": 500}])
		frappe.db.set_value(
			"Plan Category", frappe.db.get_value("Plan", server_plan, "category"),
			"provision_target", "Server",
		)
		with self.assertRaises(frappe.ValidationError):
			subscriptions.provision_service_subscription(self.TEAM, server_plan, cluster="mumbai")


class TestDualModeIngestion(IntegrationTestCase):
	"""Usage lands as one rollup row per period in both reporting modes (ADR 0015):
	Authoritative replaces the period total; Incremental accumulates deltas, deduped by
	a monotonic sequence cursor."""

	TEAM = "svc-team-ingest"

	def setUp(self):
		from central.billing.revenue import metering

		self.metering = metering
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="INR")
		frappe.db.delete("Subscription", {"team": self.TEAM})
		frappe.db.delete("Usage Rollup", {"team": self.TEAM})

	def _subject(self, resource_type, plan):
		res = subscriptions.provision_service_subscription(self.TEAM, plan, cluster="mumbai")
		return res["service_subject"]

	def _meter(self, subject, resource_type, key, qty, sequence=0):
		return {
			"resource_id": subject, "resource_type": resource_type, "meter_type": "Counter",
			"period_start": "2026-07-01 00:00:00", "period_end": "2026-07-31 23:59:59",
			"quantity": qty, "unit": "unit", "idempotency_key": key, "sequence": sequence,
		}

	def _qty(self, subject):
		return frappe.utils.flt(frappe.db.get_value("Usage Rollup", {"resource_id": subject}, "quantity"))

	def test_authoritative_repush_replaces(self):
		plan = _make_metered_family("SM Auth Family", "PDF Auth", "SM PDF Auth Plan")
		subject = self._subject("PDF Auth", plan)
		key = f"{subject}|Counter|2026-07"
		self.metering.ingest_rollup(self._meter(subject, "PDF Auth", key, 100))
		self.metering.ingest_rollup(self._meter(subject, "PDF Auth", key, 250))
		self.assertEqual(self._qty(subject), 250)  # replaced, not summed

	def test_incremental_accumulates_and_dedupes(self):
		plan = _make_metered_family(
			"SM Incr Family", "PDF Incr", "SM PDF Incr Plan", reporting_mode="Incremental"
		)
		subject = self._subject("PDF Incr", plan)
		key = f"{subject}|Counter|2026-07"
		self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 100, sequence=1))
		self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 50, sequence=2))
		self.assertEqual(self._qty(subject), 150)

		# A retried batch (same sequence) and an out-of-order older batch are no-ops.
		self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 50, sequence=2))
		self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 999, sequence=1))
		self.assertEqual(self._qty(subject), 150)

		# A new higher sequence accumulates again.
		self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 25, sequence=3))
		self.assertEqual(self._qty(subject), 175)

	def test_incremental_stays_one_row_per_period(self):
		plan = _make_metered_family(
			"SM Incr Family", "PDF Incr", "SM PDF Incr Plan", reporting_mode="Incremental"
		)
		subject = self._subject("PDF Incr", plan)
		key = f"{subject}|Counter|2026-07"
		for seq in range(1, 21):
			self.metering.ingest_rollup(self._meter(subject, "PDF Incr", key, 1, sequence=seq))
		self.assertEqual(frappe.db.count("Usage Rollup", {"resource_id": subject}), 1)
		self.assertEqual(self._qty(subject), 20)


class TestServiceAPI(IntegrationTestCase):
	"""The pilot-authenticated service facade (ADR 0015): list/subscribe/get/report,
	with the team fixed from the credential so a pilot only touches its own team."""

	TEAM = "svc-team-api"
	OTHER = "svc-team-other"

	def setUp(self):
		import inspect

		from central.billing.api import billing_api

		# Fully unwrap the whitelist + pilot-auth decorators to reach the facade body,
		# then exercise it with a stubbed credential (there is no request in tests).
		self.list_service_plans = inspect.unwrap(billing_api.list_service_plans)
		self.subscribe_service = inspect.unwrap(billing_api.subscribe_service)
		self.get_service_subscription = inspect.unwrap(billing_api.get_service_subscription)
		self.report_usage = inspect.unwrap(billing_api.report_usage)
		for t in (self.TEAM, self.OTHER):
			ensure_team(t)
			complete_billing_profile(t, currency="INR")
			frappe.db.delete("Subscription", {"team": t})
		frappe.db.delete("Usage Rollup", {"team": self.TEAM})
		self.plan = _make_metered_family("SM API Family", "PDF API", "SM PDF API Plan")
		self._act_as(self.TEAM)

	def _act_as(self, team):
		frappe.local.pilot_credential = frappe._dict(team=team)

	def test_list_service_plans_priced_for_team_currency(self):
		out = self.list_service_plans(cluster="mumbai")
		self.assertEqual(out["currency"], "INR")
		self.assertIn(self.plan, [p["plan"] for p in out["plans"]])

	def test_subscribe_then_get_and_report(self):
		sub = self.subscribe_service(self.plan, cluster="mumbai")
		subject = sub["service_subject"]

		services = self.get_service_subscription()["services"]
		self.assertIn(subject, [s["service_subject"] for s in services])

		res = self.report_usage(
			service_subject=subject, resource_type="PDF API", quantity=500,
			period_start="2026-07-01 00:00:00", period_end="2026-07-31 23:59:59",
			idempotency_key=f"{subject}|Counter|2026-07",
		)
		self.assertTrue(res["recorded"])
		self.assertEqual(
			frappe.utils.flt(frappe.db.get_value("Usage Rollup", {"resource_id": subject}, "quantity")),
			500,
		)

	def test_report_usage_for_foreign_subject_is_rejected(self):
		# A subject owned by another team must not be reportable by this credential.
		self._act_as(self.OTHER)
		foreign = self.subscribe_service(self.plan, cluster="mumbai")["service_subject"]
		self._act_as(self.TEAM)
		with self.assertRaises(frappe.PermissionError):
			self.report_usage(
				service_subject=foreign, resource_type="PDF API", quantity=10,
				period_start="2026-07-01 00:00:00", period_end="2026-07-31 23:59:59",
				idempotency_key=f"{foreign}|Counter|2026-07",
			)


class TestPrepaidSettlement(IntegrationTestCase):
	"""A Prepaid Pack family draws its allowance down as usage lands, blocks at zero,
	and bills no overage — the pack is paid up front (ADR 0015)."""

	TEAM = "svc-team-prepaid"

	def setUp(self):
		from central.billing.revenue import metering

		self.metering = metering
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="INR")
		frappe.db.delete("Subscription", {"team": self.TEAM})
		frappe.db.delete("Usage Rollup", {"team": self.TEAM})
		self.plan = _make_metered_family(
			"SM Prepaid Family", "Tokens Pre", "SM Tokens Pack",
			settlement_mode="Prepaid Pack", allowance=1000, rate=0.01,
		)
		res = subscriptions.provision_service_subscription(self.TEAM, self.plan, cluster="mumbai")
		self.subject = res["service_subject"]

	def _report(self, qty):
		self.metering.ingest_rollup({
			"resource_id": self.subject, "resource_type": "Tokens Pre", "meter_type": "Counter",
			"period_start": "2026-07-01 00:00:00", "period_end": "2026-07-31 23:59:59",
			"quantity": qty, "unit": "unit", "idempotency_key": f"{self.subject}|Counter|2026-07",
		})

	def test_within_allowance_not_blocked(self):
		from central.billing.catalog.services import service_allowance

		self._report(400)
		state = service_allowance(self.TEAM, self.subject)
		self.assertEqual(state["remaining"], 600)
		self.assertFalse(state["blocked"])

	def test_exhausted_allowance_blocks(self):
		from central.billing.catalog.services import service_allowance

		self._report(1000)
		state = service_allowance(self.TEAM, self.subject)
		self.assertEqual(state["remaining"], 0)
		self.assertTrue(state["blocked"])

	def test_prepaid_usage_bills_no_overage(self):
		# 1500 used against a 1000 pack — a postpaid family would bill 500 of overage; a
		# prepaid one bills nothing (excess is blocked, not charged).
		self._report(1500)
		lines = self.metering.metered_line_items(
			self.TEAM, "mumbai", "2026-07-01", "2026-07-31"
		)
		self.assertEqual(lines, [])
