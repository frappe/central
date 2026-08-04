# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reconciliation — charged-but-never-webhooked (issue #21)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.gateways.base import PaymentResult
from central.billing.payments import reconciliation
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-recon"
GATEWAY = "GW-Test-Stripe"


@contextmanager
def gateway_status(status):
	adapter = MagicMock()
	adapter.get_transaction_status.return_value = status
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


@contextmanager
def charge_result(success=True, txn_id="pi_x"):
	"""A gateway that answers a (re-sent) charge."""
	adapter = MagicMock()
	adapter.charge.return_value = PaymentResult(
		success=success,
		status="Captured" if success else "Failed",
		gateway_transaction_id=txn_id if success else None,
		failure_code=None if success else "card_declined",
		failure_reason=None if success else "declined",
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class ReconTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_stripe_gateway(GATEWAY)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Payment Attempt", "Invoice", "Payment Method"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.commit()

	def _open_invoice(self, total=1000):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"expected_collection": total,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _card(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Active",
					"gateway_method_id": "pm_card",
					"gateway_customer_id": "cus_1",
					"is_default": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _ambiguous_attempt(self, invoice, txn="pi_x", minutes_old=60, payment_method=None):
		name = (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": invoice,
					"team": TEAM,
					"gateway": GATEWAY,
					"amount": 1000,
					"currency": "INR",
					"status": "Initiated",
					"gateway_transaction_id": txn,
					"payment_method": payment_method,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes_old)
		frappe.db.set_value("Payment Attempt", name, "initiated_at", old)
		return name

	def _captured_attempt(self, invoice, txn="pi_x", minutes_old=60):
		"""A sync charge that reached Captured but whose invoice never settled —
		the lost-capture-webhook case (completed_at / resolved_by unset)."""
		name = (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": invoice,
					"team": TEAM,
					"gateway": GATEWAY,
					"amount": 1000,
					"currency": "INR",
					"status": "Captured",
					"gateway_transaction_id": txn,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes_old)
		frappe.db.set_value("Payment Attempt", name, "initiated_at", old)
		return name


class TestReconcile(ReconTestBase):
	def test_gateway_success_settles_invoice_idempotently(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv)
		with gateway_status("succeeded") as adapter:
			reconciliation.reconcile_attempt(attempt)
			reconciliation.reconcile_attempt(attempt)  # idempotent rerun
			adapter.charge.assert_not_called()  # read-only — never re-charges

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		a = frappe.get_doc("Payment Attempt", attempt)
		self.assertEqual(a.status, "Captured")
		self.assertEqual(a.resolved_by, "Reconciliation")

	def test_gateway_failure_fails_attempt_invoice_stays_open(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv)
		with gateway_status("failed"):
			reconciliation.reconcile_attempt(attempt)
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Failed")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_uncompleted_checkout_is_failed_safely(self):
		inv = self._open_invoice()
		# No payment method: a customer-present checkout the customer never finished.
		# No money can have moved, and there is nothing to re-send.
		attempt = self._ambiguous_attempt(inv, txn=None)
		with gateway_status("succeeded") as adapter:
			reconciliation.reconcile_attempt(attempt)
			adapter.get_transaction_status.assert_not_called()
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Failed")


class TestUnansweredCharge(ReconTestBase):
	"""A card charge we started and never got an answer to (ADR 0017).

	The attempt is saved before the gateway is called, so a crash leaves it Initiated
	with no transaction id. The money may or may not have moved and nothing local can
	say which — so we re-send the same request under its original key and let the
	gateway tell us, rather than guessing.
	"""

	def test_unanswered_charge_is_re_sent_with_its_original_key(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None, payment_method=self._card())
		key = frappe.db.get_value("Payment Attempt", attempt, "idempotency_key")

		with charge_result(success=True, txn_id="pi_replayed") as adapter:
			out = reconciliation.reconcile_attempt(attempt)

		self.assertEqual(adapter.charge.call_args.args[2], key)  # same key, so no double charge
		self.assertTrue(out["replayed"])
		a = frappe.get_doc("Payment Attempt", attempt)
		self.assertEqual(a.status, "Captured")
		self.assertEqual(a.gateway_transaction_id, "pi_replayed")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")

	def test_declined_on_re_send_fails_the_attempt(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None, payment_method=self._card())
		with charge_result(success=False):
			reconciliation.reconcile_attempt(attempt)
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Failed")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_too_old_to_re_send_is_left_alone_and_alerted(self):
		# Past the gateway's key window, re-sending would be a second charge — and
		# marking it Failed would let the next retry mint a new key and do the same.
		# So it stays Initiated and a human is told.
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None, payment_method=self._card())
		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=30)

		with charge_result(success=True) as adapter:
			out = reconciliation.reconcile_attempt(attempt, now=future)
			adapter.charge.assert_not_called()

		self.assertTrue(out["alerted"])
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Initiated")

	def test_pending_recent_is_left_unresolved(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, minutes_old=60)
		with gateway_status("requires_action"):
			out = reconciliation.reconcile_attempt(attempt, now=frappe.utils.now_datetime())
		self.assertEqual(out["unresolved"], "requires_action")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Initiated")

	def test_pending_aged_out_alerts_ops(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, minutes_old=60)
		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=30)
		with gateway_status("Pending"):
			out = reconciliation.reconcile_attempt(attempt, now=future)
		self.assertTrue(out["alerted"])
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv}, pluck="content"
		)
		self.assertTrue(any("Reconciliation" in c for c in comments))


class TestCapturedUnsettled(ReconTestBase):
	"""The lost-capture-webhook hole: attempt Captured, invoice stranded Open."""

	def test_captured_but_open_invoice_is_settled_on_gateway_success(self):
		inv = self._open_invoice()
		attempt = self._captured_attempt(inv)
		with gateway_status("succeeded") as adapter:
			out = reconciliation.reconcile_captured_attempt(attempt)
			reconciliation.reconcile_captured_attempt(attempt)  # idempotent rerun
			adapter.charge.assert_not_called()  # read-only

		self.assertEqual(out["resolved"], "paid")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		a = frappe.get_doc("Payment Attempt", attempt)
		self.assertEqual(a.status, "Captured")
		self.assertEqual(a.resolved_by, "Reconciliation")
		self.assertTrue(a.completed_at)

	def test_captured_not_confirmed_by_gateway_leaves_invoice_open(self):
		inv = self._open_invoice()
		attempt = self._captured_attempt(inv)
		with gateway_status("requires_action"):
			out = reconciliation.reconcile_captured_attempt(attempt, now=frappe.utils.now_datetime())
		self.assertEqual(out["unresolved"], "requires_action")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_captured_already_paid_invoice_is_skipped(self):
		inv = self._open_invoice()
		frappe.db.set_value("Invoice", inv, "status", "Paid")
		attempt = self._captured_attempt(inv)
		with gateway_status("succeeded") as adapter:
			out = reconciliation.reconcile_captured_attempt(attempt)
			adapter.get_transaction_status.assert_not_called()  # no gateway call once settled
		self.assertEqual(out["skipped"], "invoice_settled")

	def test_scan_settles_aged_captured_unsettled(self):
		inv = self._open_invoice()
		self._captured_attempt(inv, minutes_old=60)
		with gateway_status("succeeded"):
			reconciliation.run_reconciliation()
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")

	def test_scan_grace_window_excludes_fresh_captured(self):
		inv = self._open_invoice()
		fresh = self._captured_attempt(inv, minutes_old=5)  # within 30-min grace
		with gateway_status("succeeded"):
			results = reconciliation.run_reconciliation()
		self.assertNotIn(fresh, [r.get("attempt") for r in results])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")


class TestScan(ReconTestBase):
	def test_grace_window_excludes_fresh_attempts(self):
		inv = self._open_invoice()
		fresh = self._ambiguous_attempt(inv, minutes_old=5)  # within 30-min grace
		with gateway_status("succeeded"):
			results = reconciliation.run_reconciliation()
		self.assertNotIn(fresh, [r.get("attempt") for r in results])
		self.assertEqual(frappe.db.get_value("Payment Attempt", fresh, "status"), "Initiated")

	def test_scan_resolves_aged_ambiguous(self):
		inv = self._open_invoice()
		old = self._ambiguous_attempt(inv, minutes_old=60)
		with gateway_status("succeeded"):
			reconciliation.run_reconciliation()
		self.assertEqual(frappe.db.get_value("Payment Attempt", old, "status"), "Captured")
