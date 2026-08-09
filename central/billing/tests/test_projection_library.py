# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The shelf of canned questions."""

import frappe

from central.billing.projection import library, scenario
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
	set_team_tier,
)

TEAM = "team-library"
CLUSTER = "ap-south-1"
PLAN = "bundle-library"
TODAY = "2026-08-06"


class LibraryTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": 6000}])
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 6000, "2026-01-01 00:00:00")
		set_team_tier(TEAM, level="t1", max_spend=100000)
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Prepaid")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for name in frappe.get_all("Billing Scenario", pluck="name"):
			frappe.delete_doc("Billing Scenario", name, force=True, ignore_permissions=True)
		frappe.db.delete("Invoice", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()


class TestTheCatalogue(LibraryTestBase):
	def test_every_entry_says_what_it_asks_and_what_to_look_for(self):
		# A catalogue entry with no explanation is a button nobody presses twice.
		for entry in library.catalogue():
			self.assertTrue(entry["title"])
			self.assertTrue(entry["question"].endswith("?"))
			self.assertTrue(entry["look_for"])

	def test_entries_are_declarative_so_adding_one_needs_no_engine_change(self):
		for key, entry in library.SCENARIOS.items():
			self.assertIsInstance(entry.get("overrides", {}), dict, key)
			self.assertIsInstance(entry.get("events", []), list, key)


class TestApplicability(LibraryTestBase):
	def test_a_scenario_that_cannot_apply_says_why(self):
		# Applying a threshold scenario to a team nothing is auto-charged for would
		# demonstrate nothing and imply plenty.
		ok, reason = library.applicable("over-the-inr-threshold", TEAM)
		self.assertFalse(ok)
		self.assertIn("Auto Charge", reason)

	def test_it_applies_once_the_team_is_on_that_mode(self):
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Auto Charge")
		frappe.db.commit()
		ok, _reason = library.applicable("over-the-inr-threshold", TEAM)
		self.assertTrue(ok)

	def test_building_an_inapplicable_scenario_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			library.build("over-the-inr-threshold", TEAM, today=TODAY)

	def test_an_unknown_key_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			library.build("no-such-scenario", TEAM, today=TODAY)


class TestBuilding(LibraryTestBase):
	def test_a_scenario_is_built_but_not_saved(self):
		before = frappe.db.count("Billing Scenario")
		library.build("no-way-to-pay", TEAM, today=TODAY)
		self.assertEqual(frappe.db.count("Billing Scenario"), before)

	def test_relative_events_land_inside_the_projected_month(self):
		doc = library.build("resized-twice-in-a-day", TEAM, period_start="2026-09-01", today=TODAY)
		dates = [frappe.utils.getdate(e.on_date) for e in doc.events]
		self.assertEqual(len(dates), 2)
		self.assertTrue(all(str(d).startswith("2026-09") for d in dates))

	def test_a_doubling_event_doubles_the_rate_the_team_is_actually_on(self):
		doc = library.build("resized-twice-in-a-day", TEAM, period_start="2026-09-01", today=TODAY)
		rates = sorted(frappe.utils.flt(e.rate) for e in doc.events)
		self.assertEqual(rates, [6000.0, 12000.0])

	def test_the_harsher_ladder_carries_its_overrides(self):
		doc = library.build("harsher-dunning", TEAM, today=TODAY)
		self.assertEqual(doc.suspend_after_days, 7)
		self.assertEqual(doc.terminate_after_days, 30)

	def test_the_price_rise_targets_the_plans_the_team_runs(self):
		doc = library.build("a-price-rise", TEAM, period_start="2026-09-01", today=TODAY)
		self.assertTrue(doc.rate_overrides)
		self.assertEqual(doc.rate_overrides[0].priced_for, PLAN)
		self.assertEqual(doc.rate_overrides[0].percent, 20)


class TestWhatTheyDemonstrate(LibraryTestBase):
	def test_the_churn_scenario_really_does_push_a_date_hourly(self):
		doc = library.build("resized-twice-in-a-day", TEAM, period_start="2026-09-01", today=TODAY)
		out = scenario.project(doc, today=TODAY)
		hourly = [li for li in out["invoice"]["lines"] if li["unit"] == "hour"]
		self.assertTrue(hourly, "the catalogue entry must demonstrate what it claims")

	def test_the_harsher_ladder_really_does_move_the_suspension_left(self):
		plain = scenario.project(library.build("no-way-to-pay", TEAM, today=TODAY), today=TODAY)
		harsh = scenario.project(library.build("harsher-dunning", TEAM, today=TODAY), today=TODAY)

		def suspend_on(out):
			return next(s["date"] for s in out["calendar"]["if_never_paid"] if s["stage"] == "Suspend")

		self.assertLess(suspend_on(harsh), suspend_on(plain))

	def test_the_price_rise_really_does_change_almost_nothing(self):
		# The entry whose whole point is that the expected answer is wrong.
		doc = library.build("a-price-rise", TEAM, period_start="2026-09-01", today=TODAY)
		out = scenario.compare(doc, today=TODAY)
		self.assertEqual(out["live"]["invoice"]["total"], out["altered"]["invoice"]["total"])
		self.assertIn("locked", out["explanation"])

	def test_the_top_up_scenario_really_does_close_a_shortfall(self):
		doc = library.build("rescued-by-a-top-up", TEAM, period_start="2026-09-01", today=TODAY)
		out = scenario.project(doc, today=TODAY)
		self.assertTrue(any(e["event"] == "Topped up" for e in out["events"]))
