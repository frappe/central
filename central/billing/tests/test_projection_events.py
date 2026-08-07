# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Things that have not happened, rated as if they had."""

import frappe
from central.billing.projection import engine, events, scenario
from central.billing.projection.basis import ASSUMED, MEASURED
from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
	set_team_tier,
)

TEAM = "team-events"
CLUSTER = "ap-south-1"
PLAN = "bundle-events"
TODAY = "2026-08-06"


class EventTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 3000, "2026-01-01 00:00:00")
		set_team_tier(TEAM, level="t1", max_spend=50000)
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for name in frappe.get_all("Billing Scenario", pluck="name"):
			frappe.delete_doc("Billing Scenario", name, force=True, ignore_permissions=True)
		for dt in ("Invoice", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _project(self, events_list, **kw):
		frappe.db.commit()
		return engine.project(
			TEAM, "2026-09-01", "2026-09-30", today=TODAY, events=events_list, **kw
		)


class TestTheChangeStreamIsInjectable(EventTestBase):
	def test_without_injection_the_ledger_is_read(self):
		out = self._project(None)
		self.assertEqual(out["invoice"]["subtotal"], 3000.0)

	def test_an_injected_resize_reprices_the_rest_of_the_month(self):
		# Rated by the production line engine, so day-weighting comes for free.
		out = self._project(
			[
				{
					"event_type": events.RESIZE,
					"on_date": "2026-09-16 00:00:00",
					"subscription": self.sub,
					"plan": PLAN,
					"rate": 6000,
				}
			]
		)
		# 15 days at 3000 + 15 days at 6000 over a 30-day month.
		self.assertEqual(out["invoice"]["subtotal"], 4500.0)

	def test_a_resize_inside_the_churn_window_bills_that_date_hourly(self):
		# The sub-24h rule is the line engine's, and an invented change gets it too.
		out = self._project(
			[
				{"event_type": events.RESIZE, "on_date": "2026-09-15 09:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 6000},
				{"event_type": events.RESIZE, "on_date": "2026-09-15 18:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 3000},
			]
		)
		hourly = [li for li in out["invoice"]["lines"] if li["unit"] == "hour"]
		self.assertTrue(hourly, "a config held under 24h should push its date hourly")

	def test_an_injected_cancel_closes_the_segment(self):
		out = self._project(
			[
				{"event_type": events.CANCEL, "on_date": "2026-09-16 00:00:00",
				 "subscription": self.sub}
			]
		)
		self.assertEqual(out["invoice"]["subtotal"], 1500.0)  # 15 of 30 days

	def test_the_real_ledger_is_never_written(self):
		before = frappe.db.count("Subscription Change", {"subscription": self.sub})
		self._project(
			[
				{"event_type": events.RESIZE, "on_date": "2026-09-16 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 6000}
			]
		)
		self.assertEqual(
			frappe.db.count("Subscription Change", {"subscription": self.sub}), before
		)


class TestInventedLinesSaySo(EventTestBase):
	def test_a_line_from_an_injected_event_is_assumed_not_measured(self):
		out = self._project(
			[
				{"event_type": events.RESIZE, "on_date": "2026-09-16 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 6000}
			]
		)
		bases = {li["basis"] for li in out["invoice"]["lines"]}
		self.assertIn(ASSUMED, bases)
		self.assertIn(MEASURED, bases)

	def test_the_totals_carry_the_assumption_through(self):
		out = self._project(
			[
				{"event_type": events.RESIZE, "on_date": "2026-09-16 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 6000}
			]
		)
		self.assertGreater(out["invoice"]["assumed"], 0)
		self.assertTrue(out["invoice"]["has_estimates"])

	def test_a_projection_with_no_events_stays_measured(self):
		out = self._project(None)
		self.assertTrue(all(li["basis"] == MEASURED for li in out["invoice"]["lines"]))


class TestRefusals(EventTestBase):
	def test_a_provision_beyond_the_cap_is_reported_as_refused(self):
		# A scenario that could not happen is a finding, not a projection.
		set_team_tier(TEAM, level="t1", max_spend=1000)
		out = self._project(
			[
				{"event_type": events.PROVISION, "on_date": "2026-09-10 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 9000}
			]
		)
		self.assertTrue(out["refused"])
		self.assertIn("cap", out["refused"][0]["reason"].lower())

	def test_a_provision_within_the_cap_is_not_refused(self):
		set_team_tier(TEAM, level="t1", max_spend=50000)
		out = self._project(
			[
				{"event_type": events.PROVISION, "on_date": "2026-09-10 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 900}
			]
		)
		self.assertEqual(out["refused"], [])


class TestTheTimeline(EventTestBase):
	def test_injected_events_are_dated_and_marked_hypothetical(self):
		out = self._project(
			[
				{"event_type": events.RESIZE, "on_date": "2026-09-16 00:00:00",
				 "subscription": self.sub, "plan": PLAN, "rate": 6000}
			]
		)
		self.assertEqual(len(out["injected_events"]), 1)
		self.assertTrue(out["injected_events"][0]["hypothetical"])
		self.assertEqual(out["injected_events"][0]["date"], "2026-09-16")

	def test_they_are_kept_apart_from_what_the_roll_forward_actually_did(self):
		# Two different things were briefly both called "events"; they are not the same.
		out = engine.project_months(
			TEAM, "2026-09-01", months=2, today=TODAY,
			events=[
				{"event_type": events.TOP_UP, "on_date": "2026-09-10 00:00:00",
				 "amount": 5000, "currency": "INR"}
			],
		)
		self.assertIn("injected_events", out)
		self.assertIn("events", out)
		self.assertEqual(len(out["injected_events"]), 1)


class TestTopUps(EventTestBase):
	def test_an_injected_top_up_reaches_the_wallet_before_the_bill_is_drawn(self):
		out = engine.project_months(
			TEAM, "2026-09-01", months=2, today=TODAY,
			events=[
				{"event_type": events.TOP_UP, "on_date": "2026-09-10 00:00:00",
				 "amount": 5000, "currency": "INR"}
			],
		)
		first = out["months"][0]
		self.assertEqual(first["settlement"]["from_credits"], 3000.0)
		self.assertEqual(first["settlement"]["shortfall"], 0.0)

	def test_without_the_top_up_the_month_is_short(self):
		out = engine.project_months(TEAM, "2026-09-01", months=2, today=TODAY)
		self.assertEqual(out["months"][0]["settlement"]["shortfall"], 3000.0)

	def test_the_top_up_is_recorded_on_the_way_through(self):
		out = engine.project_months(
			TEAM, "2026-09-01", months=2, today=TODAY,
			events=[
				{"event_type": events.TOP_UP, "on_date": "2026-09-10 00:00:00",
				 "amount": 5000, "currency": "INR"}
			],
		)
		self.assertTrue(any(e["event"] == "Topped up" for e in out["events"]))

	def test_no_credit_ledger_entry_is_written(self):
		before = frappe.db.count("Credit Ledger Entry", {"team": TEAM})
		engine.project_months(
			TEAM, "2026-09-01", months=2, today=TODAY,
			events=[
				{"event_type": events.TOP_UP, "on_date": "2026-09-10 00:00:00",
				 "amount": 5000, "currency": "INR"}
			],
		)
		self.assertEqual(frappe.db.count("Credit Ledger Entry", {"team": TEAM}), before)


class TestThroughAScenario(EventTestBase):
	def test_a_saved_scenario_carries_its_events(self):
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": "What if they double in September",
				"team": TEAM,
				"period_start": "2026-09-01",
				"months": 1,
				"outcome_mode": "Derived",
				"events": [
					{
						"event_type": "Resize",
						"on_date": "2026-09-16 00:00:00",
						"subscription": self.sub,
						"plan": PLAN,
						"rate": 6000,
					}
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		out = scenario.project(doc, today=TODAY)
		self.assertEqual(out["invoice"]["subtotal"], 4500.0)
		self.assertEqual(len(out["scenario"]["events"]), 1)

	def test_the_control_side_of_a_comparison_drops_the_events(self):
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": "Resize mid-month",
				"team": TEAM,
				"period_start": "2026-09-01",
				"months": 1,
				"outcome_mode": "Derived",
				"events": [
					{
						"event_type": "Resize",
						"on_date": "2026-09-16 00:00:00",
						"subscription": self.sub,
						"plan": PLAN,
						"rate": 6000,
					}
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		out = scenario.compare(doc, today=TODAY)
		self.assertEqual(out["live"]["invoice"]["subtotal"], 3000.0)
		self.assertEqual(out["altered"]["invoice"]["subtotal"], 4500.0)
