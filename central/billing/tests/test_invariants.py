# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The money invariants that span tables — rung 4 of ADR 0018.

Each test breaks one invariant deliberately (by raw SQL, since every legitimate code
path is now blocked from breaking it) and asserts the audit catches it. A check that
cannot be made to fire is a check nobody should trust.
"""

import frappe

from central.billing.platform import invariants
from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-invariants"


class InvariantTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()

	def tearDown(self):
		self._purge()
		frappe.db.commit()

	def _purge(self):
		frappe.db.delete("Credit Ledger Entry", {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.commit()

	def _mine(self, violations, check):
		"""Only this team's violations — the site carries other teams' data."""
		return [v for v in violations if v.team == TEAM and v.check == check]


class TestWalletMatchesLedger(InvariantTestBase):
	def test_a_healthy_wallet_reports_nothing(self):
		credits.purchase(TEAM, 500, "INR")
		credits.apply_credit(TEAM, 200, "INR", reference_name="INV-1")

		self.assertEqual(self._mine(invariants.audit("C2"), "C2"), [])

	def test_anchor_drifting_from_its_ledger_is_caught(self):
		credits.purchase(TEAM, 500, "INR")
		wallet = credits.wallet_name(TEAM, "INR")

		# Raw SQL: every code path is now guarded, so drift can only be simulated by
		# going around them — which is exactly the scenario the audit exists for.
		frappe.db.sql("update `tabCredit Wallet` set balance = 430 where name = %s", (wallet,))

		found = self._mine(invariants.audit("C2"), "C2")
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0].expected, 500)  # what the ledger says
		self.assertEqual(found[0].actual, 430)  # what the anchor claims
		self.assertEqual(found[0].drift, -70)
		self.assertEqual(found[0].currency, "INR")

	def test_ledger_with_no_anchor_is_caught(self):
		credits.purchase(TEAM, 300, "INR")
		frappe.db.sql("delete from `tabCredit Wallet` where team = %s", (TEAM,))

		found = self._mine(invariants.audit("C2"), "C2")
		self.assertEqual(len(found), 1)
		self.assertIn("no Credit Wallet anchor", found[0].detail)

	def test_drift_is_reported_per_currency(self):
		credits.purchase(TEAM, 500, "INR")
		credits.purchase(TEAM, 80, "USD")
		frappe.db.sql(
			"update `tabCredit Wallet` set balance = 10 where name = %s",
			(credits.wallet_name(TEAM, "USD"),),
		)

		found = self._mine(invariants.audit("C2"), "C2")
		self.assertEqual([(v.currency, v.expected, v.actual) for v in found], [("USD", 80, 10)])


class TestRunningBalanceChain(InvariantTestBase):
	def test_an_intact_chain_reports_nothing(self):
		credits.purchase(TEAM, 500, "INR")
		credits.apply_credit(TEAM, 120, "INR", reference_name="INV-1")
		credits.purchase(TEAM, 30, "INR")

		self.assertEqual(self._mine(invariants.audit("C4"), "C4"), [])

	def test_a_deleted_ledger_entry_breaks_the_chain(self):
		credits.purchase(TEAM, 100, "INR")
		second = credits.purchase(TEAM, 50, "INR")["ledger_entry"]
		credits.purchase(TEAM, 25, "INR")

		# Excise the middle entry. The final running_balance still *looks* plausible,
		# which is precisely why the chain — not just the total — has to be checked.
		frappe.db.sql("delete from `tabCredit Ledger Entry` where name = %s", (second,))

		found = self._mine(invariants.audit("C4"), "C4")
		self.assertEqual(len(found), 1)
		self.assertIn("chain breaks here", found[0].detail)

	def test_only_the_first_break_is_reported(self):
		"""Everything after a break is the same defect, not N defects."""
		credits.purchase(TEAM, 100, "INR")
		second = credits.purchase(TEAM, 50, "INR")["ledger_entry"]
		credits.purchase(TEAM, 25, "INR")
		credits.purchase(TEAM, 25, "INR")
		frappe.db.sql("delete from `tabCredit Ledger Entry` where name = %s", (second,))

		self.assertEqual(len(self._mine(invariants.audit("C4"), "C4")), 1)


class TestPaidNeverExceedsCaptured(InvariantTestBase):
	"""P2 — an invoice may not be Paid for more than the gateway ever captured.

	It is an INEQUALITY, and the two silent cases below are why. Both are real histories
	taken from live data, and both would trip any equality:

	  - a fully-refunded invoice keeps `amount_paid` and stays Paid (a dispute refunds to
	    source; the invoice is not un-billed), so "captured minus refunds" flags it;
	  - a charge → refund → re-charge leaves TWO money-taking attempts on one invoice, so
	    "sum of captured equals amount_paid" flags that one.

	Both were found by running this audit against real data, and both are guarded here so
	the check can never be "tightened" back into crying wolf.
	"""

	def _paid_invoice(self, total, amount_paid, attempts):
		inv = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"status": "Paid",
				"currency": "INR",
				"period_start": "2098-03-01",
				"period_end": "2098-03-31",
				"subtotal": total,
				"total": total,
				"amount_paid": amount_paid,
			}
		).insert(ignore_permissions=True)
		# retry_number is part of the attempt's gateway key, so each attempt on one
		# invoice carries its own — as the charge path does.
		for retry, (amount, status) in enumerate(attempts):
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": inv.name,
					"team": TEAM,
					"amount": amount,
					"currency": "INR",
					"status": status,
					"retry_number": retry,
				}
			).insert(ignore_permissions=True)
		return inv.name

	def tearDown(self):
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Invoice", {"team": TEAM})
		super().tearDown()

	def test_a_captured_attempt_covers_the_invoice(self):
		self._paid_invoice(500, 500, [(500, "Captured")])
		self.assertEqual(self._mine(invariants.audit("P2"), "P2"), [])

	def test_a_fully_refunded_invoice_is_not_a_violation(self):
		# Refunded to source; the invoice stays Paid by design. amount_paid is intact.
		self._paid_invoice(500, 500, [(500, "Refunded")])
		self.assertEqual(self._mine(invariants.audit("P2"), "P2"), [])

	def test_charge_refund_recharge_is_not_a_violation(self):
		# Two money-taking attempts for one invoice — legitimate history, not drift.
		self._paid_invoice(500, 500, [(500, "Refunded"), (500, "Captured"), (500, "Failed")])
		self.assertEqual(self._mine(invariants.audit("P2"), "P2"), [])

	def test_paid_with_nothing_captured_behind_it_is_caught(self):
		"""The defect worth catching: revenue we believe we collected and did not."""
		self._paid_invoice(500, 500, [(500, "Failed")])

		found = self._mine(invariants.audit("P2"), "P2")
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0].expected, 0)  # nothing was ever captured
		self.assertEqual(found[0].actual, 500)  # but the invoice claims it was paid

	def test_paid_for_more_than_was_captured_is_caught(self):
		self._paid_invoice(500, 500, [(200, "Captured")])

		found = self._mine(invariants.audit("P2"), "P2")
		self.assertEqual(len(found), 1)
		self.assertEqual((found[0].expected, found[0].actual), (200, 500))


class TestAuditRunner(InvariantTestBase):
	def test_every_registered_check_runs_and_returns_a_list(self):
		for key, (title, fn) in invariants.CHECKS.items():
			with self.subTest(check=key):
				self.assertTrue(title)
				self.assertIsInstance(fn(), list)

	def test_a_broken_check_does_not_blind_the_others(self):
		"""One raising check must not take the audit down with it."""
		credits.purchase(TEAM, 500, "INR")
		frappe.db.sql(
			"update `tabCredit Wallet` set balance = 1 where name = %s",
			(credits.wallet_name(TEAM, "INR"),),
		)

		def explode():
			raise RuntimeError("check is broken")

		original = invariants.CHECKS["I1"]
		invariants.CHECKS["I1"] = ("deliberately broken", explode)
		try:
			found = invariants.audit()
		finally:
			invariants.CHECKS["I1"] = original

		# C2 still reported despite I1 blowing up.
		self.assertEqual(len(self._mine(found, "C2")), 1)

	def test_run_invariant_audit_summarises_by_check(self):
		credits.purchase(TEAM, 500, "INR")
		frappe.db.sql(
			"update `tabCredit Wallet` set balance = 0 where name = %s",
			(credits.wallet_name(TEAM, "INR"),),
		)

		result = invariants.run_invariant_audit()

		self.assertGreaterEqual(result["violations"], 1)
		self.assertGreaterEqual(result["by_check"].get("C2", 0), 1)
