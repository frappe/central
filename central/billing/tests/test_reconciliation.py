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
GATEWAY = "Stripe"


@contextmanager
def gateway_status(status):
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
	adapter.get_transaction_status.return_value = status
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


@contextmanager
def charge_result(success=True, txn_id="pi_x"):
	"""A gateway that answers a (re-sent) charge."""
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
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
		make_stripe_gateway()
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in (
			"Payment Attempt",
			"Invoice",
			"Payment Method",
			"Top-up Order",
			"Credit Ledger Entry",
			"Credit Wallet",
		):
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
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "failure_code"), "gateway_failed")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_uncompleted_checkout_is_failed_after_a_day(self):
		inv = self._open_invoice()
		# No payment method: a customer-present checkout the customer never finished.
		# No money can have moved, and there is nothing to re-send.
		attempt = self._ambiguous_attempt(inv, txn=None, minutes_old=25 * 60)
		with gateway_status("succeeded") as adapter:
			reconciliation.reconcile_attempt(attempt)
			adapter.get_transaction_status.assert_not_called()
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Failed")
		self.assertEqual(
			frappe.db.get_value("Payment Attempt", attempt, "failure_code"), "checkout_abandoned"
		)

	def test_a_slow_checkout_is_left_open(self):
		"""A UPI collect or 3DS checkout can take a while; it is not failed in its first day."""
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None)
		frappe.db.set_value("Payment Attempt", attempt, "gateway_order_id", "order_slow")
		with gateway_status("created") as adapter:
			adapter.find_order_payment.return_value = None
			out = reconciliation.reconcile_attempt(attempt)
		self.assertEqual(out["unresolved"], "awaiting_payer")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Initiated")

	def test_a_checkout_on_a_gateway_without_order_lookup_is_left_open(self):
		"""A gateway that cannot look an order up (PayPal) does not stop the scan."""
		from central.billing.gateways.base import GatewayUnsupported

		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None)
		frappe.db.set_value("Payment Attempt", attempt, "gateway_order_id", "order_paypal")
		with gateway_status("created") as adapter:
			adapter.find_order_payment.side_effect = GatewayUnsupported("no order lookup")
			out = reconciliation.reconcile_attempt(attempt)
		self.assertEqual(out["unresolved"], "awaiting_payer")

	def test_a_checkout_paid_without_a_callback_is_settled(self):
		from central.billing.gateways.base import VerifiedPayment

		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None)
		frappe.db.set_value("Payment Attempt", attempt, "gateway_order_id", "order_paid")
		with gateway_status("created") as adapter:
			adapter.find_order_payment.return_value = VerifiedPayment(
				"pay_late", True, 1000, "INR", order_id="order_paid"
			)
			reconciliation.reconcile_attempt(attempt)
		self.assertEqual(
			frappe.db.get_value("Payment Attempt", attempt, "gateway_transaction_id"), "pay_late"
		)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")


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

	def test_a_gateway_timeout_on_one_attempt_does_not_stop_the_scan(self):
		from central.billing.gateways.base import GatewayTimeout

		inv = self._open_invoice()
		unreachable = self._ambiguous_attempt(inv, txn="pi_timeout", minutes_old=60)
		# Two attempts on one invoice need different keys.
		frappe.db.set_value("Payment Attempt", unreachable, "idempotency_key", "key-timeout")
		answered = self._ambiguous_attempt(inv, txn="pi_answered", minutes_old=60)

		def transaction_status(txn):
			if txn == "pi_timeout":
				raise GatewayTimeout("timed out")
			return "succeeded"

		with gateway_status("succeeded") as adapter:
			adapter.get_transaction_status.side_effect = transaction_status
			results = reconciliation.run_reconciliation()

		self.assertNotIn(unreachable, [result.get("attempt") for result in results])
		self.assertIn(answered, [result.get("attempt") for result in results])
		self.assertEqual(frappe.db.get_value("Payment Attempt", unreachable, "status"), "Initiated")
		self.assertEqual(frappe.db.get_value("Payment Attempt", answered, "status"), "Captured")


class TestTopUpReconciliation(ReconTestBase):
	"""A top-up whose callback and webhook were both lost is credited from the gateway."""

	def _order(self, order_id, hours_old=1):
		from central.billing.doctype.top_up_order.top_up_order import TopupOrder

		order = TopupOrder.start(TEAM, GATEWAY, "INR", 700, credit=700)
		order.record_gateway_order(order_id)
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-hours_old)
		frappe.db.set_value("Top-up Order", order.name, "creation", old, update_modified=False)
		return order.name

	def test_a_paid_top_up_is_credited(self):
		from central.billing.gateways.base import VerifiedPayment
		from central.billing.revenue import credits

		order = self._order("pi_lost")
		with gateway_status("succeeded") as adapter:
			adapter.find_order_payment.return_value = VerifiedPayment(
				"pi_lost", True, 700, "INR", order_id="pi_lost"
			)
			reconciliation.reconcile_top_up_orders()
		self.assertEqual(frappe.db.get_value("Top-up Order", order, "status"), "Credited")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 700)

	def test_a_short_top_up_fails_without_stopping_the_run(self):
		from central.billing.gateways.base import VerifiedPayment

		short = self._order("pi_short")
		paid = self._order("pi_paid")
		with gateway_status("succeeded") as adapter:
			adapter.find_order_payment.side_effect = lambda order_id: VerifiedPayment(
				order_id, True, 100 if order_id == "pi_short" else 700, "INR", order_id=order_id
			)
			reconciliation.reconcile_top_up_orders()

		self.assertEqual(frappe.db.get_value("Top-up Order", short, "status"), "Failed")
		self.assertTrue(frappe.db.get_value("Top-up Order", short, "failure_reason"))
		self.assertEqual(frappe.db.get_value("Top-up Order", paid, "status"), "Credited")

	def test_an_unpaid_top_up_expires(self):
		order = self._order("pi_never", hours_old=8 * 24)
		with gateway_status("requires_payment_method") as adapter:
			adapter.find_order_payment.return_value = None
			reconciliation.reconcile_top_up_orders()
		self.assertEqual(frappe.db.get_value("Top-up Order", order, "status"), "Expired")
