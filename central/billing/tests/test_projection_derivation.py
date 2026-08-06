# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Why a line is the amount it is.

The derivation has to come from the computation that produced the amount, not from a
second pass that re-derives it — a second pass is just a parallel model with a shorter
life expectancy. So the line builders emit it, and only when asked.
"""

import frappe
from central.billing.projection import engine
from central.billing.revenue.invoicing.lines import compute_line_items
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_metered_plan,
	make_plan,
)

TEAM = "team-derivation"
CLUSTER = "ap-south-1"
PLAN = "bundle-derivation"
JUNE = ("2026-06-01", "2026-06-30")


class DerivationTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN, includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}])
		make_metered_plan(
			"meter-transfer-derivation",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Usage Rollup"):
			frappe.db.delete(dt, {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _lines(self, explain=True):
		return compute_line_items(TEAM, CLUSTER, *JUNE, explain=explain)


class TestItIsOptIn(DerivationTestBase):
	def test_the_run_gets_exactly_what_it_always_got(self):
		# The billing run must not start carrying an explanation into Invoice Line Item.
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		self.assertTrue(all("derivation" not in line for line in self._lines(explain=False)))

	def test_asking_changes_no_amount(self):
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		plain = [li["amount"] for li in self._lines(explain=False)]
		explained = [li["amount"] for li in self._lines(explain=True)]
		self.assertEqual(plain, explained)


class TestDailyLines(DerivationTestBase):
	def test_a_stable_month_shows_its_arithmetic(self):
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		line = self._lines()[0]
		d = line["derivation"]

		self.assertEqual(d["mode"], "Daily")
		self.assertEqual(d["days"], 30)
		self.assertEqual(d["day_units"], 30)
		self.assertEqual(d["locked_rate"], 3000.0)
		self.assertEqual(d["arithmetic"], "30 ÷ 30 × 3000.0")
		self.assertEqual(line["amount"], 3000.0)

	def test_the_dates_it_billed_are_named(self):
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		d = self._lines()[0]["derivation"]
		self.assertEqual(len(d["dates"]), 30)
		self.assertEqual(d["dates"][0], "2026-06-01")
		self.assertEqual(d["dates"][-1], "2026-06-30")

	def test_a_mid_month_change_splits_into_two_explained_segments(self):
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		add_segment(self.sub, "Plan Changed", 6000, "2026-06-16 00:00:00")
		lines = sorted(self._lines(), key=lambda li: li["derivation"]["segment_from"])

		self.assertEqual([li["derivation"]["days"] for li in lines], [15, 15])
		self.assertEqual([li["derivation"]["locked_rate"] for li in lines], [3000.0, 6000.0])


class TestChurnDates(DerivationTestBase):
	def setUp(self):
		super().setUp()
		# 2000 all month, bumped to 4000 for nine hours on the 15th.
		add_segment(self.sub, "Created", 2000, "2026-06-01 00:00:00")
		add_segment(self.sub, "Plan Changed", 4000, "2026-06-15 09:00:00")
		add_segment(self.sub, "Plan Changed", 2000, "2026-06-15 18:00:00")

	def test_an_hourly_line_says_why_the_date_went_hourly(self):
		hourly = [li for li in self._lines() if li["unit"] == "hour"]
		self.assertTrue(hourly)
		why = hourly[0]["derivation"]["why"]
		self.assertIn("less than 24 hours", why)

	def test_it_names_every_config_that_shared_the_date(self):
		# This is the answer to "why is my bill itemised by the hour on the 15th".
		hourly = [li for li in self._lines() if li["unit"] == "hour"]
		configs = hourly[0]["derivation"]["configs_on_this_date"]
		self.assertEqual(len(configs), 3)
		self.assertTrue(any(c["held_under_24h"] for c in configs))

	def test_the_two_passes_partition_the_month_without_overlap(self):
		# Daily and hourly must tile the period exactly: no date billed twice, none
		# missed. This is the property that keeps the total exact.
		lines = self._lines()
		daily_dates = [d for li in lines if li["unit"] == "day" for d in li["derivation"]["dates"]]
		hourly_dates = {
			d for li in lines if li["unit"] == "hour" for d in li["derivation"]["dates"]
		}

		self.assertEqual(len(daily_dates), len(set(daily_dates)), "a date was billed twice daily")
		self.assertFalse(set(daily_dates) & hourly_dates, "a date was billed daily and hourly")
		self.assertEqual(len(set(daily_dates) | hourly_dates), 30, "the month was not covered")

	def test_the_hourly_arithmetic_is_shown_against_the_hour_denominator(self):
		hourly = [li for li in self._lines() if li["unit"] == "hour"]
		d = hourly[0]["derivation"]
		self.assertEqual(d["hour_units"], 720)  # 30 days × 24
		self.assertIn("÷ 720 ×", d["arithmetic"])


class TestMeteredLines(DerivationTestBase):
	def _rollup(self, quantity):
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": frappe.db.get_value("Subscription", self.sub, "asset_id"),
				"team": TEAM,
				"cluster": CLUSTER,
				"resource_type": "Transfer",
				"meter_type": "Counter",
				"period_start": "2026-06-01 00:00:00",
				"period_end": "2026-06-30 23:59:59",
				"quantity": quantity,
				"unit": "GB",
				"currency": "INR",
				"locked_allowance": 100,
				"locked_rate": 0.5,
				"idempotency_key": "deriv:2026-06",
				"sequence": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_overage_shows_measured_quantity_allowance_and_rate_source(self):
		from central.billing.revenue.metering import metered_line_items

		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		self._rollup(340)
		line = metered_line_items(TEAM, CLUSTER, *JUNE, explain=True)[0]
		d = line["derivation"]

		self.assertEqual(d["measured_quantity"], 340.0)
		self.assertEqual(d["allowance"], 100.0)
		self.assertEqual(d["billable_quantity"], 240.0)
		self.assertEqual(d["rate_source"], "locked at ingest")
		self.assertEqual(d["arithmetic"], "max(0, 340.0 − 100.0) × 0.5")


class TestThroughTheProjection(DerivationTestBase):
	def test_every_projected_line_carries_its_derivation(self):
		add_segment(self.sub, "Created", 3000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertTrue(all("derivation" in li for li in out["invoice"]["lines"]))

	def test_a_grandfathered_rate_is_visible_as_the_locked_one(self):
		# The drill is where an operator learns that raising a catalog rate would not
		# reach this subscription.
		add_segment(self.sub, "Created", 3000, "2026-03-14 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertEqual(out["invoice"]["lines"][0]["derivation"]["locked_rate"], 3000.0)
