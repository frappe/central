# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit ledger + wallet + concurrency (issue #06)."""

import threading

import frappe

from central.billing.platform.constraints import existing_constraints
from central.billing.revenue import credits
from central.billing.revenue.credits import InsufficientCredits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import billing_settings, ensure_team

TEAM = "team-wallet"


def yesterday():
	return frappe.utils.add_days(frappe.utils.nowdate(), -1)


def run_workers(n: int, fn):
	"""Run `fn(i)` in n threads, each on its own DB connection, and return a
	dict {i: "ok" | exception-class-name}. Each worker commits on success so the
	FOR UPDATE locking is exercised across real concurrent transactions."""
	site = frappe.local.site
	results = {}

	def worker(i):
		frappe.init(site=site)
		frappe.connect()
		frappe.set_user("Administrator")
		try:
			fn(i)
			frappe.db.commit()
			results[i] = "ok"
		except Exception as e:
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


class CreditTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		# Threads commit to the DB, so clean up explicitly (not via test rollback).
		frappe.db.delete("Credit Ledger Entry", {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.delete("Billing Group", {"team": TEAM})
		frappe.db.commit()


class TestLedgerBasics(CreditTestBase):
	def test_balance_is_zero_with_no_entries(self):
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_purchase_credits_raises_balance(self):
		res = credits.purchase(TEAM, 500, "INR")
		self.assertEqual(res["new_balance"], 500)
		self.assertEqual(credits.get_balance(TEAM)["balance"], 500)

	def test_balance_equals_signed_ledger_sum(self):
		credits.purchase(TEAM, 500)
		credits.apply_credit(TEAM, 120, reference_type="Invoice", reference_name="INV-1")
		credits.purchase(TEAM, 30)

		entries = frappe.get_all("Credit Ledger Entry", {"team": TEAM}, ["entry_type", "amount"])
		signed = sum((e.amount if e.entry_type == "Credit" else -e.amount) for e in entries)
		self.assertEqual(signed, 410)
		# Balance read equals the ledger sum — it is never a stored scalar.
		self.assertEqual(credits.get_balance(TEAM)["balance"], signed)

	def test_running_balance_recorded_on_each_entry(self):
		credits.purchase(TEAM, 500)
		res = credits.apply_credit(TEAM, 200, reference_name="INV-1")
		self.assertEqual(res["new_balance"], 300)
		latest = frappe.get_all(
			"Credit Ledger Entry",
			{"team": TEAM, "entry_type": "Debit"},
			pluck="running_balance",
		)
		self.assertEqual(latest, [300])

	def test_debit_beyond_balance_raises_and_leaves_balance_intact(self):
		credits.purchase(TEAM, 100)
		with self.assertRaises(InsufficientCredits):
			credits.apply_credit(TEAM, 150)
		self.assertEqual(credits.get_balance(TEAM)["balance"], 100)

	def test_non_positive_amount_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			credits.purchase(TEAM, 0)
		with self.assertRaises(frappe.ValidationError):
			credits.apply_credit(TEAM, -10)

	def test_entry_is_append_only(self):
		credits.purchase(TEAM, 100)
		name = frappe.get_all("Credit Ledger Entry", {"team": TEAM}, pluck="name")[0]
		doc = frappe.get_doc("Credit Ledger Entry", name)
		doc.amount = 999
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_admin_adjustment_books_an_entry(self):
		credits.purchase(TEAM, 100)
		res = credits.adjust_credits(TEAM, 25, "Debit", note="dispute clawback")
		self.assertEqual(res["new_balance"], 75)

	def test_get_balance_filtered_by_currency(self):
		credits.purchase(TEAM, 500, "INR")
		credits.purchase(TEAM, 100, "USD")
		credits.purchase(TEAM, 100, "INR")

		# A currency-filtered read sums only that currency's entries and excludes
		# the others (here the USD top-up does not leak into the INR balance).
		self.assertEqual(credits.get_balance(TEAM, currency="INR")["balance"], 600)
		self.assertEqual(credits.get_balance(TEAM, currency="USD")["balance"], 100)

	def test_get_balance_unfiltered_uses_the_team_currency(self):
		"""Omitting currency reads the team's BILLING currency, not a blind sum.

		It used to return the newest entry's currency-blind `running_balance` — i.e.
		INR + USD added together as bare floats. Nothing is summed across currencies
		now; the unfiltered read is simply the team's own currency (ADR 0018).
		"""
		credits.purchase(TEAM, 300, "INR")
		credits.purchase(TEAM, 50, "USD")

		result = credits.get_balance(TEAM)
		self.assertEqual(result["currency"], "INR")  # TEAM's billing currency
		self.assertEqual(result["balance"], 300)  # NOT 350

	def test_get_balances_lists_each_currency_separately(self):
		credits.purchase(TEAM, 300, "INR")
		credits.purchase(TEAM, 50, "USD")

		balances = {b["currency"]: b["balance"] for b in credits.get_balances(TEAM)}
		self.assertEqual(balances, {"INR": 300, "USD": 50})


class TestNonNegativePerCurrency(CreditTestBase):
	"""The wallet may not go negative — in EVERY currency it holds, not just overall.

	The anchor was once one currency-blind float per team, so the debit guard compared
	a USD debit against a balance that included the team's INR credits. A team could be
	driven negative in USD while the anchor stayed positive. The anchor is now keyed
	(team, currency), so the guard is per-currency by construction (ADR 0018).
	"""

	def test_usd_debit_cannot_be_funded_by_inr_credits(self):
		credits.purchase(TEAM, 1000, "INR")
		credits.purchase(TEAM, 10, "USD")

		# 50 USD against a 10 USD balance. The team holds 1000 INR, which under the
		# old currency-blind anchor would have made this debit "affordable".
		with self.assertRaises(InsufficientCredits):
			credits.apply_credit(TEAM, 50, "USD", reference_name="INV-USD")

		self.assertEqual(credits.get_balance(TEAM, "USD")["balance"], 10)
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 1000)

	def test_debiting_one_currency_leaves_the_other_untouched(self):
		credits.purchase(TEAM, 1000, "INR")
		credits.purchase(TEAM, 80, "USD")

		credits.apply_credit(TEAM, 30, "USD", reference_name="INV-USD")

		self.assertEqual(credits.get_balance(TEAM, "USD")["balance"], 50)
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 1000)

	def test_anchor_agrees_with_the_ledger_per_currency(self):
		"""Invariant C2: the anchor equals the signed ledger sum, for each currency."""
		credits.purchase(TEAM, 500, "INR")
		credits.purchase(TEAM, 90, "USD")
		credits.apply_credit(TEAM, 200, "INR", reference_name="INV-1")
		credits.apply_credit(TEAM, 40, "USD", reference_name="INV-2")

		for currency, expected in (("INR", 300), ("USD", 50)):
			self.assertEqual(credits.get_balance(TEAM, currency)["balance"], expected)
			self.assertEqual(credits.ledger_balance(TEAM, currency), expected)

	def test_the_check_constraint_is_actually_installed(self):
		"""The constraint must exist on EVERY site, not just ones that migrated.

		Frappe marks patches as executed without running them on a fresh install, so a
		constraint declared only in a patch is silently absent on new sites — a fresh
		site quietly weaker than a migrated one. It is applied from an
		after_install/after_migrate hook instead, and this test is what keeps that true.
		"""
		self.assertIn(
			"credit_wallet_balance_non_negative",
			existing_constraints("tabCredit Wallet"),
		)

	def test_check_constraint_refuses_a_negative_balance_from_raw_sql(self):
		"""The rung that actually holds: `set_value` skips the controller entirely.

		This is the write `credits.py` itself performs, so a Python guard alone would
		leave the invariant unenforced against our own code.
		"""
		credits.purchase(TEAM, 100, "INR")
		wallet = credits.wallet_name(TEAM, "INR")

		with self.assertRaises(Exception) as ctx:
			frappe.db.set_value("Credit Wallet", wallet, "balance", -1, update_modified=False)
			frappe.db.commit()
		frappe.db.rollback()
		self.assertIn("credit_wallet_balance_non_negative", str(ctx.exception).lower())


class TestConcurrency(CreditTestBase):
	def test_ten_threads_apply_credits_no_double_spend(self):
		credits.purchase(TEAM, 100, "INR")  # seed wallet
		frappe.db.commit()  # make the seed visible to the worker connections

		results = run_workers(
			10,
			lambda i: credits.apply_credit(
				TEAM, 10, "INR", reference_type="Invoice", reference_name=f"INV-{i}"
			),
		)

		# All ten fit within the balance and succeed.
		self.assertTrue(all(v == "ok" for v in results.values()), results)

		frappe.db.rollback()  # refresh the main connection's snapshot
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)
		# running_balance is the exact cumulative ladder — no gaps, no negatives.
		debit_balances = sorted(
			frappe.get_all(
				"Credit Ledger Entry", {"team": TEAM, "entry_type": "Debit"}, pluck="running_balance"
			)
		)
		self.assertEqual(debit_balances, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
		self.assertEqual(frappe.db.count("Credit Ledger Entry", {"team": TEAM}), 11)

	def test_contended_overdraw_is_prevented(self):
		credits.purchase(TEAM, 50, "INR")  # only 5 of the 10 debits can fit
		frappe.db.commit()

		results = run_workers(
			10,
			lambda i: credits.apply_credit(TEAM, 10, "INR", reference_name=f"INV-{i}"),
		)

		oks = [v for v in results.values() if v == "ok"]
		fails = [v for v in results.values() if v == "InsufficientCredits"]
		self.assertEqual(len(oks), 5)
		self.assertEqual(len(fails), 5)

		frappe.db.rollback()
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)
		balances = frappe.get_all("Credit Ledger Entry", {"team": TEAM}, pluck="running_balance")
		self.assertTrue(all(b >= 0 for b in balances))  # never negative

	def test_cross_team_bookings_do_not_deadlock(self):
		"""Concurrent bookings for DIFFERENT teams must not deadlock. Each booking
		locks only its own wallet anchor (a single PK row, no gap locks) and reads
		the balance off it, so bookings never contend on the shared ledger index.
		Regression guard for the `creation`-index gap-lock deadlock that earlier
		struck cross-team bookings despite each holding its own wallet lock."""
		teams = [f"{TEAM}-x{i}" for i in range(8)]
		for t in teams:
			ensure_team(t)
			frappe.db.delete("Credit Ledger Entry", {"team": t})
			frappe.db.delete("Credit Wallet", {"team": t})
			credits.purchase(t, 1000, "INR")
		frappe.db.commit()  # make the seeds visible to the worker connections

		try:
			# Several rounds of all teams booking at once — high cross-team contention.
			for rnd in range(5):
				results = run_workers(
					len(teams),
					lambda i, rnd=rnd: credits.apply_credit(
						teams[i], 10, "INR", reference_name=f"INV-x{i}-{rnd}"
					),
				)
				self.assertTrue(all(v == "ok" for v in results.values()), results)

			frappe.db.rollback()  # refresh the main connection's snapshot
			for t in teams:
				# 1000 seed − 5×10 debited; anchor and ledger agree.
				self.assertEqual(credits.get_balance(t)["balance"], 950)
				anchor = credits.wallet_name(t, "INR")
				self.assertEqual(frappe.db.get_value("Credit Wallet", anchor, "balance"), 950)
		finally:
			for t in teams:
				frappe.db.delete("Credit Ledger Entry", {"team": t})
				frappe.db.delete("Credit Wallet", {"team": t})
			frappe.db.commit()


class TestCreditExpiry(CreditTestBase):
	"""Promotional credit runs out of time; purchased credit does not."""

	def _grant(self, amount, expires_on, currency="INR"):
		return credits.grant_promotional_credits(TEAM, amount, currency, expires_on=expires_on)[
			"ledger_entry"
		]

	def test_purchased_credit_has_no_expiry(self):
		entry = credits.purchase(TEAM, 500, "INR")["ledger_entry"]
		self.assertIsNone(frappe.db.get_value("Credit Ledger Entry", entry, "expires_on"))

	def test_grant_stamps_the_configured_validity(self):
		with billing_settings(promotional_credit_validity_days=30):
			entry = credits.grant_promotional_credits(TEAM, 100, "INR")["ledger_entry"]

		self.assertEqual(
			frappe.db.get_value("Credit Ledger Entry", entry, "expires_on"),
			frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), 30)),
		)

	def test_zero_validity_grants_credit_that_never_expires(self):
		with billing_settings(promotional_credit_validity_days=0):
			entry = credits.grant_promotional_credits(TEAM, 100, "INR")["ledger_entry"]

		self.assertIsNone(frappe.db.get_value("Credit Ledger Entry", entry, "expires_on"))

	def test_expiry_writes_off_only_what_is_left(self):
		self._grant(100, yesterday())
		credits.apply_credit(TEAM, 40, "INR", reference_name="INV-1")

		written_off = credits.expire_credits(TEAM, "INR")

		self.assertEqual([e["amount"] for e in written_off], [60])
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_expiry_leaves_purchased_credit_alone(self):
		self._grant(100, yesterday())
		credits.purchase(TEAM, 500, "INR")

		credits.expire_credits(TEAM, "INR")

		self.assertEqual(credits.get_balance(TEAM)["balance"], 500)

	def test_debits_spend_the_soonest_expiring_credit_first(self):
		"""Credit about to die is spent before credit that never will."""
		self._grant(100, frappe.utils.add_days(frappe.utils.nowdate(), 1))
		credits.purchase(TEAM, 100, "INR")
		credits.apply_credit(TEAM, 100, "INR", reference_name="INV-1")

		# The debit came out of the grant, so nothing is left to expire tomorrow.
		lots = {lot.name: lot.remaining for lot in credits.credit_lots(TEAM, "INR")}
		self.assertEqual(sorted(lots.values()), [0.0, 100.0])
		self.assertEqual(
			credits.expire_credits(TEAM, "INR", frappe.utils.add_days(frappe.utils.nowdate(), 2)),
			[],
		)
		self.assertEqual(credits.get_balance(TEAM)["balance"], 100)

	def test_grants_expire_in_date_order(self):
		self._grant(100, yesterday())
		self._grant(50, frappe.utils.add_days(frappe.utils.nowdate(), 10))
		credits.apply_credit(TEAM, 30, "INR", reference_name="INV-1")

		written_off = credits.expire_credits(TEAM, "INR")

		# The debit came out of the grant expiring first, leaving 70 of it to sweep;
		# the later grant is untouched.
		self.assertEqual([e["amount"] for e in written_off], [70])
		self.assertEqual(credits.get_balance(TEAM)["balance"], 50)

	def test_sweeping_twice_writes_off_once(self):
		self._grant(100, yesterday())

		credits.expire_credits(TEAM, "INR")
		self.assertEqual(credits.expire_credits(TEAM, "INR"), [])
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)
		self.assertEqual(
			frappe.db.count("Credit Ledger Entry", {"team": TEAM, "reference_type": "Expiry"}), 1
		)

	def test_expiry_never_drives_the_wallet_negative(self):
		self._grant(100, yesterday())
		credits.apply_credit(TEAM, 100, "INR", reference_name="INV-1")

		self.assertEqual(credits.expire_credits(TEAM, "INR"), [])
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_wallet_still_equals_its_ledger_after_a_sweep(self):
		self._grant(100, yesterday())
		credits.purchase(TEAM, 25, "INR")
		credits.expire_credits(TEAM, "INR")

		self.assertEqual(credits.get_balance(TEAM)["balance"], credits.ledger_balance(TEAM, "INR"))

	def test_expiring_credits_lists_what_has_not_expired_yet(self):
		self._grant(100, frappe.utils.add_days(frappe.utils.nowdate(), 5))
		credits.purchase(TEAM, 500, "INR")

		upcoming = credits.expiring_credits(TEAM, "INR")

		self.assertEqual(len(upcoming), 1)
		self.assertEqual(upcoming[0]["amount"], 100)
		self.assertEqual(
			upcoming[0]["expires_on"],
			frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), 5)),
		)

	def test_the_daily_sweep_finds_the_wallet(self):
		self._grant(100, yesterday())

		result = credits.run_credit_expiry()

		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)
		self.assertGreaterEqual(result["entries"], 1)


class TestBillingGroupBudgets(CreditTestBase):
	"""No new wallets: a Billing Group's "budget" is a computed subset of the ONE
	(team, currency) wallet, derived from which Credit Ledger Entries got tagged
	with it. Isolation (no fallback either direction) is enforced in
	`credits._post_entry`, not just hoped for by callers."""

	def _group(self, title="Customer X", enabled=1):
		return frappe.get_doc(
			{"doctype": "Billing Group", "title": title, "team": TEAM, "enabled": enabled}
		).insert().name

	def test_tagged_purchase_raises_the_group_budget_not_the_general_pool(self):
		group = self._group()
		credits.purchase(TEAM, 500, "INR", billing_group=group)

		self.assertEqual(credits.group_budget(TEAM, "INR", group), 500)
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 0)
		# The wallet's real total is unaffected by how it's earmarked.
		self.assertEqual(credits.get_balance(TEAM)["balance"], 500)

	def test_untagged_purchase_raises_only_the_general_pool(self):
		group = self._group()
		credits.purchase(TEAM, 300, "INR")

		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 300)
		self.assertEqual(credits.group_budget(TEAM, "INR", group), 0)

	def test_group_debit_cannot_exceed_its_own_budget_even_with_pool_funds_available(self):
		group = self._group()
		credits.purchase(TEAM, 100, "INR", billing_group=group)
		credits.purchase(TEAM, 1000, "INR")  # plenty in the general pool

		with self.assertRaises(InsufficientCredits):
			credits.apply_credit(TEAM, 150, "INR", reference_name="INV-1", billing_group=group)

		# Nothing moved — the general pool is untouched by the failed group debit.
		self.assertEqual(credits.group_budget(TEAM, "INR", group), 100)
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 1000)

	def test_general_debit_cannot_dip_into_a_reserved_group_budget(self):
		group = self._group()
		credits.purchase(TEAM, 500, "INR", billing_group=group)
		credits.purchase(TEAM, 50, "INR")  # general pool has only 50

		with self.assertRaises(InsufficientCredits):
			credits.apply_credit(TEAM, 100, "INR", reference_name="INV-1")

		self.assertEqual(credits.group_budget(TEAM, "INR", group), 500)
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 50)

	def test_two_groups_never_share_each_others_budget(self):
		x = self._group("Customer X")
		y = self._group("Customer Y")
		credits.purchase(TEAM, 200, "INR", billing_group=x)
		credits.purchase(TEAM, 50, "INR", billing_group=y)

		with self.assertRaises(InsufficientCredits):
			credits.apply_credit(TEAM, 100, "INR", reference_name="INV-Y", billing_group=y)

		self.assertEqual(credits.group_budget(TEAM, "INR", x), 200)
		self.assertEqual(credits.group_budget(TEAM, "INR", y), 50)

	def test_disabling_a_group_folds_its_leftover_budget_into_the_general_pool(self):
		group = self._group()
		credits.purchase(TEAM, 400, "INR", billing_group=group)
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 0)

		frappe.db.set_value("Billing Group", group, "enabled", 0)

		# No ledger transaction needed — excluding a disabled group from "reserved"
		# is all it takes for its leftover to become spendable by the general pool.
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 400)
		# The entries are still tagged with the (now-disabled) group's name; only the
		# *reservation* changed, not the ledger history.
		self.assertEqual(credits.group_budget(TEAM, "INR", group), 400)

	def test_refund_to_wallet_can_be_tagged_back_to_its_originating_group(self):
		# Unit-level: refunds.py's own use of this (resolving the invoice's
		# billing_group and threading it through) is covered in test_refunds.py,
		# which already has the Payment Attempt / Refund fixtures for it.
		group = self._group()
		credits.purchase(TEAM, 200, "INR", billing_group=group)
		credits.apply_credit(TEAM, 150, "INR", reference_name="INV-1", billing_group=group)
		self.assertEqual(credits.group_budget(TEAM, "INR", group), 50)

		credits.refund_to_wallet(TEAM, 60, "INR", reference_name="INV-1", billing_group=group)

		self.assertEqual(credits.group_budget(TEAM, "INR", group), 110)
		self.assertEqual(credits.general_pool_balance(TEAM, "INR"), 0)

	def test_invariant_catches_a_group_budget_pushed_negative(self):
		from central.billing.platform import invariants

		group = self._group()
		credits.purchase(TEAM, 100, "INR", billing_group=group)
		# Simulate a write that bypassed `_post_entry`'s group guard (direct insert,
		# not through credits.py) — the wallet-level CHECK constraint alone would not
		# have caught this, since the TOTAL wallet balance can stay non-negative
		# while one group's own tag goes negative.
		frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": TEAM,
				"entry_type": "Debit",
				"amount": 150,
				"currency": "INR",
				"billing_group": group,
				"running_balance": 0,
				"created_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

		violations = invariants.check_billing_group_budget_not_negative()

		self.assertTrue(any(v.subject == group and v.team == TEAM for v in violations))
