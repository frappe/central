# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rolling a team forward: what each month leaves behind for the next."""

import frappe
from central.billing.projection import engine, state
from central.billing.projection.state import ProjectedWallet
from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-rollforward"
CLUSTER = "ap-south-1"
PLAN = "bundle-rollforward"
TODAY = "2026-08-06"


class RollForwardTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 1000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Credit Ledger Entry", "Payment Method"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _project(self, months=1, **kw):
		frappe.db.commit()
		return engine.project_months(TEAM, "2026-09-01", months=months, today=TODAY, **kw)


class TestTheWalletCarries(RollForwardTestBase):
	def test_credits_are_drawn_down_month_after_month(self):
		# 2,500 against a 1,000/month bill: two months covered, the third is short.
		credits.purchase(TEAM, 2500, "INR")
		out = self._project(months=3)

		months = out["months"]
		self.assertEqual(months[0]["settlement"]["from_credits"], 1000.0)
		self.assertEqual(months[1]["settlement"]["from_credits"], 1000.0)
		self.assertEqual(months[2]["settlement"]["from_credits"], 500.0)
		self.assertEqual(months[2]["settlement"]["shortfall"], 500.0)

	def test_the_balance_falls_across_the_projection(self):
		credits.purchase(TEAM, 2500, "INR")
		out = self._project(months=3)
		balances = [m["balance_after"] for m in out["months"]]
		self.assertEqual(balances, [1500.0, 500.0, 0.0])
		self.assertEqual(out["ends"]["balance"], 0.0)

	def test_the_wallet_does_not_refill_itself(self):
		# The failure this whole seam exists to prevent: reading today's balance every
		# month, so the team looks solvent forever.
		credits.purchase(TEAM, 1000, "INR")
		out = self._project(months=3)
		self.assertEqual(out["months"][1]["settlement"]["from_credits"], 0.0)
		self.assertEqual(out["months"][1]["settlement"]["shortfall"], 1000.0)


class TestExpiringCredit(RollForwardTestBase):
	def test_promotional_credit_dies_on_its_date_even_if_unspent(self):
		credits.grant_promotional_credits(
			TEAM, 5000, "INR", note="promo", expires_on="2026-09-30"
		)
		out = self._project(months=3)

		# September may spend it right up to the 30th; October opens without it.
		self.assertEqual(out["months"][0]["settlement"]["from_credits"], 1000.0)
		self.assertEqual(out["months"][1]["settlement"]["from_credits"], 0.0)
		self.assertEqual(out["months"][1]["settlement"]["shortfall"], 1000.0)
		self.assertTrue(any(e["event"] == "Credits expired" for e in out["events"]))

	def test_purchased_credit_survives(self):
		credits.purchase(TEAM, 5000, "INR")
		out = self._project(months=3)
		self.assertEqual(out["months"][2]["settlement"]["from_credits"], 1000.0)
		self.assertFalse(any(e["event"] == "Credits expired" for e in out["events"]))


class TestSuspensionStopsTheClock(RollForwardTestBase):
	def test_a_team_that_never_pays_is_suspended_and_stops_accruing(self):
		out = self._project(months=6)  # no credits, no card
		suspended = [m for m in out["months"] if m["suspended"]]

		self.assertTrue(suspended, "a team with no way to pay should reach suspension")
		self.assertIsNotNone(out["ends"]["suspended_on"])
		self.assertEqual(out["ends"]["standing"], "Suspended")

	def test_no_invoice_is_raised_after_suspension(self):
		out = self._project(months=6)
		after = [m for m in out["months"] if m["suspended"]]
		self.assertTrue(all(m["invoice"] is None for m in after))


class TestTierPromotion(RollForwardTestBase):
	def test_settled_invoices_accumulate_into_the_paid_history(self):
		# Paid history is what the trust ladder scores, so settling months has to move it.
		credits.purchase(TEAM, 20000, "INR")
		frappe.db.commit()
		seeded = state.seed(TEAM, TODAY)
		self.assertEqual(seeded.paid_count, 0)

		self._project(months=6)
		rolled = state.seed(TEAM, TODAY)
		# The projection wrote nothing, so the real history is untouched...
		self.assertEqual(rolled.paid_count, 0)

		# ...while the projection's own copy advanced with every month it settled.
		seeded.record_paid(1000)
		seeded.record_paid(1000)
		self.assertEqual(seeded.paid_count, 2)
		self.assertEqual(seeded.paid_total, 2000.0)

	def test_the_projected_cap_never_falls_below_where_the_team_started(self):
		# Nothing guarantees a ladder prices higher rungs higher. If it does not, climbing
		# it must not shrink a paying customer's ceiling.
		credits.purchase(TEAM, 20000, "INR")
		frappe.db.commit()
		start_cap = state.seed(TEAM, TODAY).tier_cap(TEAM)

		out = self._project(months=6)
		self.assertGreaterEqual(out["ends"]["tier_cap"], start_cap)


class TestASingleMonthIsUnchanged(RollForwardTestBase):
	def test_one_month_rolled_matches_the_single_period_projection(self):
		credits.purchase(TEAM, 5000, "INR")
		frappe.db.commit()
		rolled = engine.project_months(TEAM, "2026-09-01", months=1, today=TODAY)
		single = engine.project(TEAM, "2026-09-01", "2026-09-30", today=TODAY)

		self.assertEqual(
			rolled["months"][0]["invoice"]["total"], single["invoice"]["total"]
		)
		self.assertEqual(
			rolled["months"][0]["calendar"]["due_on"], single["calendar"]["due_on"]
		)

	def test_a_team_with_nothing_running_rolls_quietly(self):
		self._purge()
		frappe.db.commit()
		out = engine.project_months(TEAM, "2026-09-01", months=3, today=TODAY)
		self.assertTrue(all(m["invoice"] is None for m in out["months"]))


class TestTheWalletModel(IntegrationTestCase):
	def test_draws_take_the_soonest_expiring_lot_first(self):
		# Spending credit that is about to die before credit that never will is what
		# wastes the least of the customer's money.
		wallet = ProjectedWallet(
			[
				{"remaining": 100.0, "expires_on": "2026-09-30"},
				{"remaining": 100.0, "expires_on": None},
			]
		)
		wallet.draw(120)
		self.assertEqual(wallet.balance, 80.0)
		self.assertEqual(wallet.lots[0]["expires_on"], None)

	def test_a_draw_beyond_the_balance_takes_what_is_there(self):
		wallet = ProjectedWallet([{"remaining": 40.0, "expires_on": None}])
		self.assertEqual(wallet.draw(100), 40.0)
		self.assertEqual(wallet.balance, 0.0)

	def test_expiry_removes_only_what_is_past_its_date(self):
		wallet = ProjectedWallet(
			[
				{"remaining": 60.0, "expires_on": "2026-09-30"},
				{"remaining": 40.0, "expires_on": "2026-12-31"},
			]
		)
		self.assertEqual(wallet.expire("2026-10-01"), 60.0)
		self.assertEqual(wallet.balance, 40.0)

	def test_new_credit_sorts_into_the_queue_by_expiry(self):
		wallet = ProjectedWallet([{"remaining": 50.0, "expires_on": None}])
		wallet.credit(25, expires_on="2026-09-30")
		self.assertEqual(wallet.lots[0]["expires_on"], "2026-09-30")
