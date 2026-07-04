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
	settlement_mode="Postpaid Overage", allowance=0, rate=0.5, pricing_mode="Grandfathered",
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
			"pricing_mode": pricing_mode, "reporting_mode": reporting_mode,
			"settlement_mode": settlement_mode,
		}
	).insert(ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": "Plan", "title": plan, "category": category, "billing_cycle": "Monthly",
			"is_active": 1,
			"includes": [{"resource_type": resource_type, "quantity": allowance, "unit": "Nos"}],
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
		self.plan = make_metered_plan("Svc PDF Render", resource_type="PDF Render", unit="Nos")

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

	def test_upgrade_within_family_keeps_subject_and_relocks(self):
		# Subject is keyed on the family, so switching a team onto a newer plan in the
		# same family (a catalog swap — only one metered plan per resource type may be
		# active, ADR 0008) is an upgrade that stays on the same subject and re-locks.
		from central.billing.catalog.pricing import set_catalog_rates
		from central.billing.tests.utils import _ensure_rate_instances

		cat = "SM Upgrade Family"
		small = _make_metered_family(cat, "Tokens Up", "SM Tokens Small", rate=0.01, allowance=1000)
		first = subscriptions.provision_service_subscription(self.TEAM, small, cluster="mumbai")

		# Retire the small plan and publish a bigger one in the same family.
		frappe.db.set_value("Plan", small, "is_active", 0)
		big = frappe.get_doc(
			{
				"doctype": "Plan", "title": "SM Tokens Big", "category": cat,
				"billing_cycle": "Monthly", "is_active": 1,
				"includes": [{"resource_type": "Tokens Up", "quantity": 5000, "unit": "Nos"}],
			}
		)
		big.name = "SM Tokens Big"
		big.flags.name_set = True
		big.insert(ignore_permissions=True)
		rates = [{"cluster": "", "currency": "INR", "rate": 0.008}]
		_ensure_rate_instances(rates)
		set_catalog_rates("Plan", big.name, rates)

		upgrade = subscriptions.provision_service_subscription(self.TEAM, "SM Tokens Big", cluster="mumbai")

		self.assertEqual(first["service_subject"], upgrade["service_subject"])
		self.assertEqual(first["subscription"], upgrade["subscription"])
		self.assertTrue(upgrade["upgraded"])
		self.assertEqual(
			frappe.db.get_value("Subscription", upgrade["subscription"], "plan"), "SM Tokens Big"
		)

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
			"quantity": qty, "unit": "Nos", "idempotency_key": key, "sequence": sequence,
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

	def test_first_insert_race_reapplies_lost_delta(self):
		# Two concurrent FIRST reports both miss the not-yet-existent row and race to
		# insert; the loser hits the unique idempotency_key. Simulate that (lock-miss +
		# duplicate insert) and assert the loser's delta is re-applied to the winner's
		# row, not dropped.
		from unittest.mock import patch

		plan = _make_metered_family(
			"SM Race Family", "PDF Race", "SM PDF Race Plan", reporting_mode="Incremental"
		)
		subject = self._subject("PDF Race", plan)
		key = f"{subject}|Counter|2026-07"
		self.metering.ingest_rollup(self._meter(subject, "PDF Race", key, 100, sequence=1))  # winner

		orig_gv, orig_ins = frappe.db.get_value, self.metering._insert_rollup
		state = {"missed": False, "raised": False}

		def gv(doctype, filters=None, *a, **k):
			if (not state["missed"] and doctype == "Usage Rollup"
					and isinstance(filters, dict) and filters.get("idempotency_key") == key):
				state["missed"] = True
				return None  # our first-report lock-miss
			return orig_gv(doctype, filters, *a, **k)

		def ins(*a, **k):
			if not state["raised"]:
				state["raised"] = True
				raise frappe.DuplicateEntryError  # we lose the unique-key race
			return orig_ins(*a, **k)

		with patch.object(frappe.db, "get_value", side_effect=gv), \
				patch.object(self.metering, "_insert_rollup", side_effect=ins):
			self.metering.ingest_rollup(self._meter(subject, "PDF Race", key, 50, sequence=2))

		self.assertEqual(self._qty(subject), 150)  # 100 + 50 — the racing delta survived
		self.assertEqual(frappe.db.count("Usage Rollup", {"resource_id": subject}), 1)

	def test_exhausted_insert_race_does_not_acknowledge(self):
		# If every retry loses the race without ever persisting, ingest must return None
		# (not the key) so the reporter does not mark the batch synced over missing usage.
		from unittest.mock import patch

		plan = _make_metered_family(
			"SM Exhaust Family", "PDF Exh", "SM PDF Exh Plan", reporting_mode="Incremental"
		)
		subject = self._subject("PDF Exh", plan)
		key = f"{subject}|Counter|2026-07"
		orig_gv = frappe.db.get_value

		def gv(doctype, filters=None, *a, **k):
			if doctype == "Usage Rollup" and isinstance(filters, dict) and filters.get("idempotency_key") == key:
				return None  # every read misses
			return orig_gv(doctype, filters, *a, **k)

		def ins(*a, **k):
			raise frappe.DuplicateEntryError  # every insert loses

		with patch.object(frappe.db, "get_value", side_effect=gv), \
				patch.object(self.metering, "_insert_rollup", side_effect=ins):
			result = self.metering.ingest_rollup(self._meter(subject, "PDF Exh", key, 50, sequence=1))

		self.assertIsNone(result)  # not acknowledged
		self.assertEqual(frappe.db.count("Usage Rollup", {"resource_id": subject}), 0)

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

		# The consumer service names only the service it is + the quantity; Central
		# derives the subject, period and idempotency key from the credential.
		res = self.report_usage(service="PDF API", quantity=500, cluster="mumbai")
		self.assertTrue(res["recorded"])
		self.assertEqual(res["service_subject"], subject)
		self.assertEqual(
			frappe.utils.flt(frappe.db.get_value("Usage Rollup", {"resource_id": subject}, "quantity")),
			500,
		)

	def test_global_service_reports_from_any_cluster(self):
		# A globally-priced service is subscribed once with no cluster; a caller on any
		# cluster (or none) reports to that one team-wide subject.
		globally = self.subscribe_service(self.plan, cluster=None)["service_subject"]

		from_mumbai = self.report_usage(service="PDF API", quantity=30, cluster="mumbai")
		from_nowhere = self.report_usage(service="PDF API", quantity=70)  # authoritative replace
		self.assertEqual(from_mumbai["service_subject"], globally)
		self.assertEqual(from_nowhere["service_subject"], globally)
		self.assertEqual(
			frappe.utils.flt(frappe.db.get_value("Usage Rollup", {"resource_id": globally}, "quantity")),
			70,
		)

	def test_live_priced_service_reports_with_billing_context(self):
		# A Live-priced family reads team/cluster/currency from the meter payload; the
		# subject's segment must supply them, or the rollup lands context-less and is
		# missed at invoicing.
		from central.billing.revenue.metering import metered_line_items

		live = _make_metered_family(
			"SM Live Family", "PDF Live", "SM PDF Live Plan", pricing_mode="Live", rate=2.0
		)
		res_sub = self.subscribe_service(live, cluster=None)  # global Live service
		res = self.report_usage(service="PDF Live", quantity=300)
		subject = res_sub["service_subject"]
		self.assertTrue(res["recorded"])

		row = frappe.db.get_value(
			"Usage Rollup", {"resource_id": subject}, ["team", "cluster", "currency"], as_dict=True
		)
		self.assertEqual(row.team, self.TEAM)     # was null before the context fix
		self.assertEqual(row.currency, "INR")     # Live reads currency off the payload

		# It bills: Live reads the current catalog rate at invoice time (300 x 2.0).
		lines = metered_line_items(
			self.TEAM, row.cluster,
			frappe.utils.get_first_day(frappe.utils.nowdate()),
			frappe.utils.get_last_day(frappe.utils.nowdate()),
		)
		self.assertTrue(
			any(l["subscription_resource"] == subject and l["amount"] == 600.0 for l in lines)
		)

	def test_report_usage_for_unsubscribed_service_is_rejected(self):
		# A caller can only report for a service ITS OWN team is subscribed to — there is
		# no subject to name, so another team's usage cannot be forged.
		self._act_as(self.OTHER)  # OTHER never subscribed to PDF API
		with self.assertRaises(frappe.ValidationError):
			self.report_usage(service="PDF API", quantity=10, cluster="mumbai")


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
			"quantity": qty, "unit": "Nos", "idempotency_key": f"{self.subject}|Counter|2026-07",
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


class TestAdminServices(IntegrationTestCase):
	"""The operator console view of a team's metered services + subscribe/upgrade
	(ADR 0015). Operator-gated, team explicit (an admin acts across teams)."""

	TEAM = "svc-team-admin"

	def setUp(self):
		from central.billing.api.admin import services as admin_services

		self.admin = admin_services
		frappe.set_user("Administrator")
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="INR")
		frappe.db.delete("Subscription", {"team": self.TEAM})
		self.plan = _make_metered_family("SM Admin Family", "PDF Admin", "SM PDF Admin Plan")

	def test_get_team_services_lists_footprint_and_catalog(self):
		self.admin.subscribe_team_service(self.TEAM, self.plan, cluster="mumbai")
		out = self.admin.get_team_services(self.TEAM, cluster="mumbai")
		self.assertEqual(out["currency"], "INR")
		self.assertIn(self.plan, [s["plan"] for s in out["services"]])
		self.assertIn(self.plan, [p["plan"] for p in out["available_plans"]])

	def test_subscribe_team_service_provisions_subject(self):
		res = self.admin.subscribe_team_service(self.TEAM, self.plan, cluster="mumbai")
		self.assertTrue(res["service_subject"].startswith("svc-"))
		self.assertEqual(
			frappe.db.get_value("Subscription", res["subscription"], "team"), self.TEAM
		)
