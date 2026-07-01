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

	def test_same_day_provision_destroy_floors_to_one_day(self):
		# Provisioned and cancelled on the same day → 1 day, not 0.
		add_segment(self.sub, "Created", 1000, "2026-06-05 00:00:00")
		add_segment(self.sub, "Cancelled", None, "2026-06-05 00:00:00")

		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(len(inv.items), 1)  # cancelled marker is skipped
		self.assertEqual(inv.items[0].days, 1)
		self.assertEqual(inv.items[0].amount, round(1000 / 30, 2))

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
