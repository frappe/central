# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Postpaid two-phase invoice generation (issue #09)."""

import threading
from unittest.mock import patch

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.revenue import invoicing, credits
from central.billing.revenue.invoicing import run
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


class TestOneInvoicePerPeriod(BillingTestBase):
	"""A team is billed at most once for a period — enforced, not merely intended.

	`generate_team_invoice` read "does an invoice exist?" and then inserted, with no
	lock and no constraint in between, while `generate_draft_invoices` enqueues one job
	per team. Two workers could both read "no" and both insert. The unique index on
	`Invoice.period_key` is what makes the double bill impossible (ADR 0018, I6).
	"""

	def test_concurrent_generation_bills_the_team_exactly_once(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.commit()  # make the segment visible to the worker connections

		results = run_workers(
			6,
			lambda i: invoicing.generate_team_invoice(TEAM, "2026-06-01", "2026-06-30"),
		)
		frappe.db.rollback()  # refresh this connection's snapshot

		# Every worker returns the SAME invoice: the losers of the race yield to the
		# winner instead of raising, so a concurrent caller is indistinguishable from a
		# sequential one. Without the unique index all six inserted their own.
		self.assertEqual(len(set(results.values())), 1, results)

		live = frappe.get_all(
			"Invoice",
			filters={"team": TEAM, "period_start": "2026-06-01", "status": ["!=", "Cancelled"]},
			pluck="name",
		)
		self.assertEqual(len(live), 1, f"team billed {len(live)}x for one period: {live}")
		self.assertEqual(live, list(set(results.values())))

	def test_cancel_and_reissue_reclaims_the_period_slot(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		first = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")

		second = invoicing.reissue_invoice(first, reason="wrong rate")

		self.assertIsNotNone(second)
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Invoice", first, "status"), "Cancelled")
		# The cancelled invoice stepped out of the index so the reissue could take
		# the period's slot — but only one invoice is live for it.
		live = frappe.get_all(
			"Invoice",
			filters={"team": TEAM, "period_start": "2026-06-01", "status": ["!=", "Cancelled"]},
			pluck="name",
		)
		self.assertEqual(live, [second])

	def test_several_cancelled_invoices_coexist_for_one_period(self):
		"""Cancelling twice must not trip the unique index.

		The cancelled key is a per-invoice sentinel rather than NULL: Frappe coerces an
		unset Data field to the empty string, and empty strings COLLIDE in a unique
		index — so "null it on cancel" would have let the first cancellation through
		and rejected the second.
		"""
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		first = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		second = invoicing.reissue_invoice(first, reason="one")
		third = invoicing.reissue_invoice(second, reason="two")

		self.assertEqual(len({first, second, third}), 3)
		cancelled = frappe.get_all(
			"Invoice", filters={"team": TEAM, "status": "Cancelled"}, pluck="name"
		)
		self.assertCountEqual(cancelled, [first, second])


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

	def test_credit_debit_uses_invoice_currency(self):
		# Regression: a USD team was credited in USD but debited in INR because
		# open_and_collect didn't pass the invoice currency (apply_credit defaults INR).
		usd_team = "team-invoice-usd"
		for dt in ("Credit Ledger Entry", "Credit Wallet", "Subscription",
				   "Asset", "Billing Profile", "Invoice"):
			frappe.db.delete(dt, {"team": usd_team})
		sub = make_billing_subscription(usd_team, CLUSTER, PLAN, billing_cycle="Monthly", currency="USD")
		add_segment(sub, "Created", 100, "2026-06-01 00:00:00", currency="USD")
		name = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")
		credits.purchase(usd_team, 50, "USD")
		frappe.db.commit()

		invoicing.open_and_collect(name)

		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(inv.currency, "USD")
		self.assertEqual(inv.credit_applied, 50.0)
		debit = frappe.get_all(
			"Credit Ledger Entry", {"team": usd_team, "entry_type": "Debit"}, ["currency"]
		)
		self.assertEqual(debit[0].currency, "USD")  # debited in the invoice currency, not INR
		# The USD wallet is drawn to zero; there is no spurious INR balance.
		self.assertEqual(credits.get_balance(usd_team, "USD")["balance"], 0)
		self.assertEqual(credits.get_balance(usd_team, "INR")["balance"], 0)

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

	def test_disabled_open_segment_does_not_consume_run_rate(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.set_value("Subscription", self.sub, "enabled", 0)

		self.assertEqual(subscriptions.current_segment_rate(self.sub), 1000)
		self.assertEqual(subscriptions.team_run_rate(TEAM), 0)

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
		from central.patches.v0_0.cancel_terminated_subscriptions import (
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


class TestFanOutRun(IntegrationTestCase):
	"""The monthly run as an orchestrator: paged, fanned out, failure-isolated."""

	CLUSTER = "ap-south-1"
	PLAN = "bundle-fanout-test"
	TEAMS = ["team-fanout-a", "team-fanout-b", "team-fanout-c"]

	def setUp(self):
		make_plan(self.PLAN)
		self._purge()
		for team in self.TEAMS:
			sub = make_billing_subscription(team, self.CLUSTER, self.PLAN, billing_cycle="Monthly")
			add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		from central.billing.tests.utils import purge_teams

		purge_teams(self.TEAMS)
		frappe.db.delete("Error Log", {"method": run.BILLING_RUN_FAILURE})
		frappe.db.commit()

	def test_one_failing_team_does_not_take_the_run_down(self):
		# Team b blows up mid-run: the team drafted before it must survive (the unit
		# rolls back to its own savepoint, not the whole transaction), and the team
		# after it must still be billed.
		real = run.generate_team_invoice

		def explode(team, *args, **kwargs):
			if team == "team-fanout-b":
				raise ValueError("no rate for this team")
			return real(team, *args, **kwargs)

		with patch.object(run, "generate_team_invoice", side_effect=explode):
			run.generate_draft_invoices("2026-06-01", "2026-06-30")

		self.assertTrue(frappe.db.exists("Invoice", {"team": "team-fanout-a"}))
		self.assertFalse(frappe.db.exists("Invoice", {"team": "team-fanout-b"}))
		self.assertTrue(frappe.db.exists("Invoice", {"team": "team-fanout-c"}))

		# The casualty is logged under the one title an operator can count.
		self.assertTrue(
			frappe.db.exists(
				"Error Log", {"method": run.BILLING_RUN_FAILURE, "reference_name": "team-fanout-b"}
			)
		)

	def test_a_failed_team_is_redrafted_by_the_next_tick(self):
		# Nothing is re-raised, so the run has to be resumable: the retry drafts the
		# team that failed and does not double-bill the ones that succeeded.
		real = run.generate_team_invoice

		def explode(team, *args, **kwargs):
			if team == "team-fanout-b":
				raise ValueError("transient")
			return real(team, *args, **kwargs)

		with patch.object(run, "generate_team_invoice", side_effect=explode):
			run.generate_draft_invoices("2026-06-01", "2026-06-30")
		run.generate_draft_invoices("2026-06-01", "2026-06-30")

		for team in self.TEAMS:
			self.assertEqual(frappe.db.count("Invoice", {"team": team}), 1)

	def test_fan_out_enqueues_one_deduplicated_job_per_team(self):
		with patch("frappe.enqueue") as enqueue:
			run.generate_draft_invoices("2026-06-01", "2026-06-30", enqueue=True)

		calls = {c.kwargs["team"]: c for c in enqueue.call_args_list}
		self.assertTrue(set(self.TEAMS) <= set(calls))
		call = calls["team-fanout-a"]
		self.assertEqual(call.args[0], "central.billing.revenue.invoicing.draft_team_invoice")
		self.assertEqual(call.kwargs["queue"], run.BILLING_QUEUE)
		self.assertEqual(call.kwargs["job_id"], "billing-draft::2026-06-30::team-fanout-a")
		self.assertTrue(call.kwargs["deduplicate"])
		# The orchestrator hands out work; it must not rate anything itself.
		self.assertFalse(frappe.db.exists("Invoice", {"team": "team-fanout-a"}))

	def test_fanned_out_jobs_draft_exactly_what_the_inline_run_would(self):
		from central.billing.tests.utils import run_enqueued_inline

		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			run.generate_draft_invoices("2026-06-01", "2026-06-30", enqueue=True)

		for team in self.TEAMS:
			self.assertEqual(frappe.db.count("Invoice", {"team": team}), 1)

	def test_the_two_ticks_bill_the_closed_month_end_to_end(self):
		from central.billing.tests.utils import run_enqueued_inline

		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			drafting = run.draft_monthly_invoices(today="2026-07-01")
			collecting = run.collect_monthly_invoices(today="2026-07-01")

		# Both ticks agree on the period: the month that closed, never a live one.
		self.assertEqual(drafting["period_end"], "2026-06-30")
		self.assertEqual(collecting["period_end"], "2026-06-30")
		self.assertGreaterEqual(collecting["invoices"], len(self.TEAMS))
		for team in self.TEAMS:
			inv = frappe.get_doc("Invoice", {"team": team, "period_end": "2026-06-30"})
			self.assertNotEqual(inv.status, "Draft")

	def test_collection_tick_alone_settles_nothing(self):
		# Order matters: the collect tick only ever touches drafts that already exist,
		# so firing it before drafting is a no-op rather than a half-billed month.
		with patch("frappe.enqueue") as enqueue:
			run.collect_monthly_invoices(today="2026-07-01")

		fanned = [c.kwargs["invoice"] for c in enqueue.call_args_list]
		mine = frappe.get_all("Invoice", filters={"team": ["in", self.TEAMS]}, pluck="name")
		self.assertEqual(mine, [])
		self.assertEqual([i for i in fanned if i in mine], [])

	def test_status_shows_a_half_finished_run(self):
		from central.billing.tests.utils import run_enqueued_inline

		# Drafting only: every invoice is still waiting to be collected.
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			run.draft_monthly_invoices(today="2026-07-01")
		mid = run.billing_run_status(today="2026-07-01")
		self.assertEqual(mid["period_end"], "2026-06-30")
		self.assertGreaterEqual(mid["drafted"], len(self.TEAMS))
		self.assertEqual(mid["pending_collection"], mid["drafted"])
		self.assertEqual(mid["collected"], 0)

		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			run.collect_monthly_invoices(today="2026-07-01")
		done = run.billing_run_status(today="2026-07-01")
		self.assertEqual(done["pending_collection"], 0)
		self.assertEqual(done["collected"], done["drafted"])

	def test_status_counts_the_teams_a_failed_run_still_owes(self):
		real = run.generate_team_invoice

		def explode(team, *args, **kwargs):
			if team == "team-fanout-b":
				raise ValueError("no rate for this team")
			return real(team, *args, **kwargs)

		before = run.billing_run_status(today="2026-07-01")
		with patch.object(run, "generate_team_invoice", side_effect=explode):
			run.generate_draft_invoices("2026-06-01", "2026-06-30")
		after = run.billing_run_status(today="2026-07-01")

		self.assertEqual(after["failures"], before["failures"] + 1)
		self.assertGreaterEqual(after["pending_draft"], 1)  # team b still owes a bill

	def test_a_lost_savepoint_stops_the_run_instead_of_silencing_it(self):
		# The database restarted (or something committed underneath the unit), so the
		# savepoint is gone and the failure cannot be contained. Swallowing it would
		# leave every remaining team merely "not billed", with no cause recorded.
		def gone(*args, **kwargs):
			raise frappe.db.ProgrammingError("SAVEPOINT billing_run_unit does not exist")

		with (
			patch.object(run, "generate_team_invoice", side_effect=ValueError("the real cause")),
			patch.object(frappe.db, "rollback", side_effect=gone),
			self.assertRaises(ValueError) as raised,
		):
			run.draft_team_invoice("team-fanout-a", "2026-06-01", "2026-06-30")

		# The original cause survives — the rollback failure is its context, not a
		# replacement for it.
		self.assertEqual(str(raised.exception), "the real cause")

	def test_a_contained_failure_is_written_to_the_log_file_too(self):
		# The Error Log row is a database write: a worker killed before its commit
		# loses it. The file line is what remains, so it must always be written.
		with (
			patch.object(run, "generate_team_invoice", side_effect=ValueError("boom")),
			patch.object(frappe.logger("billing"), "error") as logged,
		):
			run.draft_team_invoice("team-fanout-a", "2026-06-01", "2026-06-30")

		self.assertEqual(logged.call_count, 1)
		self.assertIn("team-fanout-a", logged.call_args.args[0])
		self.assertIsInstance(logged.call_args.kwargs["exc_info"], ValueError)
