# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Postpaid two-phase invoice generation (issue #09)."""

import threading

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.revenue import invoicing, credits
from central.billing.tests.utils import (
	add_segment,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-invoice"
CLUSTER = "ap-south-1"
PLAN = "bundle-invoice-test"


def run_workers(n, fn):
	site = frappe.local.site
	results = {}

	def worker(i):
		frappe.init(site=site)
		frappe.connect()
		frappe.set_user("Administrator")
		try:
			results[i] = fn(i)
			frappe.db.commit()
		except Exception as e:  # noqa: BLE001
			frappe.db.rollback()
			results[i] = type(e).__name__
		finally:
			frappe.destroy()

	threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	return results


class BillingTestBase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		# Asset-model subscription; the auto 'Created' segment is cleared so each test
		# authors its own run-segment timeline with add_segment.
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()


class TestDraftGeneration(BillingTestBase):
	def test_day_weighted_line_items_new_plan_wins_the_day(self):
		# One subscription, two plan changes within June (rates 1000 / 2000 / 1000).
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		add_segment(self.sub, "Plan Changed", 2000, "2026-06-10 00:00:00")
		add_segment(self.sub, "Plan Changed", 1000, "2026-06-22 00:00:00")

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		self.assertEqual(inv.status, "Draft")
		days = sorted(li.days for li in inv.items)
		self.assertEqual(days, [9, 9, 12])  # Jun1-9, Jun22-30 (9 each), Jun10-21 (12)
		amounts = sorted(li.amount for li in inv.items)
		# 9*1000/30=300, 9*1000/30=300, 12*2000/30=800
		self.assertEqual(amounts, [300.0, 300.0, 800.0])
		self.assertEqual(inv.subtotal, 1400.0)
		self.assertEqual(inv.total, 1400.0)
		self.assertEqual(inv.expected_collection, 1400.0)

	def test_same_day_churn_bills_by_the_hour(self):
		# Provisioned 09:00 and cancelled 18:00 the same day: a sub-24h run bills its
		# real hours (9h), not a floored full day.
		add_segment(self.sub, "Created", 1000, "2026-06-05 09:00:00")
		add_segment(self.sub, "Cancelled", None, "2026-06-05 18:00:00")

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(len(inv.items), 1)  # cancelled marker is skipped
		li = inv.items[0]
		self.assertEqual(li.unit, "hour")
		self.assertEqual(li.hours, 9.0)
		self.assertEqual(li.amount, round(9 * 1000 / (30 * 24), 2))

	def test_multiple_resizes_in_a_day_bill_that_day_hourly(self):
		# 2000 all month; a peak-hours bump to 4000 (09:00) then back (18:00) on Jun 15.
		# Only Jun 15 goes hourly; the rest of the month stays daily.
		add_segment(self.sub, "Created", 2000, "2026-06-01 00:00:00")
		add_segment(self.sub, "Plan Changed", 4000, "2026-06-15 09:00:00")
		add_segment(self.sub, "Plan Changed", 2000, "2026-06-15 18:00:00")

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		daily = [li for li in inv.items if li.unit == "day"]
		hourly = [li for li in inv.items if li.unit == "hour"]
		# Jun 1–14 (14 days) + Jun 16–30 (15 days) at 2000 stay daily.
		self.assertEqual(sorted(li.days for li in daily), [14, 15])
		# Jun 15 itemised by the hour: 9h@2000, 9h@4000, 6h@2000.
		self.assertEqual(
			sorted((li.hours, li.rate) for li in hourly),
			[(6.0, 2000.0), (9.0, 2000.0), (9.0, 4000.0)],
		)
		# 29 daily days + 24 hourly hours = exactly one 30-day month of runtime, with
		# 9h billed at the higher 4000 rate. No double-count, no gap.
		self.assertEqual(inv.subtotal, 2025.0)

	def test_cross_midnight_churn_bills_both_days_hourly(self):
		# Bump 23:00 Jun 10 → drop 01:00 Jun 11 (2h, < 24h): the 24h window straddles
		# midnight, so both dates go hourly even though each has one change.
		add_segment(self.sub, "Created", 2000, "2026-06-01 00:00:00")
		add_segment(self.sub, "Plan Changed", 8000, "2026-06-10 23:00:00")
		add_segment(self.sub, "Plan Changed", 2000, "2026-06-11 01:00:00")

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		hourly = [li for li in inv.items if li.unit == "hour"]
		# 8000 ran exactly 1h on each side of midnight.
		self.assertEqual(sorted(li.hours for li in hourly if li.rate == 8000.0), [1.0, 1.0])
		# Jun 10 and Jun 11 are excluded from the daily lines (billed hourly instead).
		daily_days = sum(li.days for li in inv.items if li.unit == "day")
		self.assertEqual(daily_days, 28)  # 30 days − Jun 10 − Jun 11

	def test_partial_first_month_billed_for_join_window(self):
		add_segment(self.sub, "Created", 3000, "2026-06-15 00:00:00")
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(inv.items[0].days, 16)  # Jun15-30 inclusive
		self.assertEqual(inv.items[0].amount, round(16 * 3000 / 30, 2))

	def test_nothing_invoiced_at_sign_up(self):
		# Creating the subscription must not create any invoice.
		self.assertEqual(frappe.db.count("Invoice", {"team": TEAM}), 0)

	def test_draft_generation_is_idempotent(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		first = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		second = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Invoice", {"subscription": self.sub}), 1)

	def test_no_runtime_yields_no_invoice(self):
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertIsNone(name)


class TestOpenAndCollect(BillingTestBase):
	def _draft(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		return invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")

	def test_open_applies_credits_and_transitions(self):
		name = self._draft()  # 30 days * 1000/30 = 1000
		credits.purchase(TEAM, 400, "INR")
		frappe.db.commit()

		result = invoicing.open_and_collect(name)
		inv = frappe.get_doc("Invoice", name)
		self.assertTrue(result["claimed"])
		self.assertEqual(inv.status, "Open")
		self.assertEqual(inv.credit_applied, 400.0)
		self.assertEqual(inv.expected_collection, 600.0)
		self.assertTrue(inv.due_date)
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_parallel_open_processes_invoice_once(self):
		name = self._draft()
		credits.purchase(TEAM, 200, "INR")
		frappe.db.commit()

		results = run_workers(10, lambda i: invoicing.open_and_collect(name)["claimed"])

		claims = [r for r in results.values() if r is True]
		self.assertEqual(len(claims), 1)  # exactly one worker claimed the invoice

		frappe.db.rollback()
		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(inv.status, "Open")
		self.assertEqual(inv.credit_applied, 200.0)  # credit applied exactly once
		# One debit entry for the invoice — no duplicate debit.
		debits = frappe.get_all(
			"Credit Ledger Entry",
			{"team": TEAM, "entry_type": "Debit", "reference_name": name},
		)
		self.assertEqual(len(debits), 1)


class TestTerminationCancelsBilling(BillingTestBase):
	"""Terminating the VM must close the billing segment, not just pause it."""

	def test_terminate_cancels_segment_and_frees_run_rate(self):
		asset_id = frappe.db.get_value("Subscription", self.sub, "asset_id")
		# The VM comes up Running — that enables the subscription (Asset controller).
		asset = frappe.get_doc("Asset", asset_id)
		asset.status = "Running"
		asset.save(ignore_permissions=True)
		self.assertTrue(frappe.db.get_value("Subscription", self.sub, "enabled"))

		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		self.assertEqual(subscriptions.team_run_rate(TEAM), 1000)  # it counts while alive

		# The mirror flips to Terminated (Atlas vm.terminated / reconcile).
		asset.reload()
		asset.status = "Terminated"
		asset.save(ignore_permissions=True)

		# A Cancelled change closed the segment; the sub is disabled and stops counting.
		changes = frappe.get_all(
			"Subscription Change", {"subscription": self.sub}, pluck="change_type"
		)
		self.assertIn("Cancelled", changes)
		self.assertFalse(frappe.db.get_value("Subscription", self.sub, "enabled"))
		self.assertEqual(subscriptions.current_segment_rate(self.sub), 0)
		self.assertEqual(subscriptions.team_run_rate(TEAM), 0)  # headroom freed


class TestCancelTerminatedPatch(BillingTestBase):
	"""v26 backfill: close the open segment of VMs terminated before the runtime fix."""

	def test_patch_cancels_open_segment_on_terminated_asset(self):
		from central.billing.patches.v26_cancel_terminated_subscriptions.cancel_terminated_subscriptions import (
			cancel_terminated_subscriptions,
		)

		asset_id = frappe.db.get_value("Subscription", self.sub, "asset_id")
		frappe.db.set_value("Subscription", self.sub, "enabled", 1)
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		# Legacy bug state: the mirror was flipped to Terminated WITHOUT the controller
		# cancelling — a direct write leaves the segment open.
		frappe.db.set_value("Asset", asset_id, "status", "Terminated")
		self.assertEqual(subscriptions.team_run_rate(TEAM), 1000)

		self.assertEqual(cancel_terminated_subscriptions(), 1)

		self.assertEqual(subscriptions.current_segment_rate(self.sub), 0)
		self.assertEqual(subscriptions.team_run_rate(TEAM), 0)
		self.assertFalse(frappe.db.get_value("Subscription", self.sub, "enabled"))

		# Idempotent: a second run closes nothing (no duplicate Cancelled).
		self.assertEqual(cancel_terminated_subscriptions(), 0)
		cancels = frappe.get_all(
			"Subscription Change", {"subscription": self.sub, "change_type": "Cancelled"}
		)
		self.assertEqual(len(cancels), 1)


class TestMonthlyBillingRun(BillingTestBase):
	"""The scheduled entrypoint that drafts + settles the just-closed month."""

	def test_run_bills_and_settles_previous_month(self):
		# Ran all of June at 1000/mo; the run fires on the 1st of July.
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		credits.purchase(TEAM, 1000, "INR")  # credits cover it → settled in full
		frappe.db.commit()

		result = invoicing.run_monthly_billing(today="2026-07-01")

		self.assertEqual(result["period_start"], "2026-06-01")
		self.assertEqual(result["period_end"], "2026-06-30")

		# The team's June invoice was drafted and opened (here, credits settle it).
		inv = frappe.get_doc("Invoice", {"team": TEAM, "period_end": "2026-06-30"})
		self.assertNotEqual(inv.status, "Draft")
		self.assertEqual(inv.status, "Paid")
		self.assertEqual(inv.credit_applied, 1000.0)

	def test_run_is_idempotent(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.commit()

		invoicing.run_monthly_billing(today="2026-07-01")
		# A second tick must not double-bill the period.
		invoicing.run_monthly_billing(today="2026-07-01")

		self.assertEqual(
			frappe.db.count("Invoice", {"team": TEAM, "period_end": "2026-06-30"}), 1
		)
