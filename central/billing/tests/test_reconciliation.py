# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reconciliation — charged-but-never-webhooked (issue #21)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.payments import reconciliation
from central.billing.tests.test_stripe_adapter import make_stripe_gateway

TEAM = "team-recon"
GATEWAY = "GW-Test-Stripe"


@contextmanager
def gateway_status(status):
	adapter = MagicMock()
	adapter.get_transaction_status.return_value = status
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class ReconTestBase(IntegrationTestCase):
	def setUp(self):
		make_stripe_gateway(GATEWAY)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Payment Attempt", "Invoice"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.commit()

	def _open_invoice(self, total=1000):
		return frappe.get_doc(
			{
				"doctype": "Invoice", "team": TEAM, "invoice_type": "billable", "status": "Open",
				"period_start": "2026-05-01", "period_end": "2026-05-31", "currency": "INR",
				"subtotal": total, "total": total, "expected_collection": total,
			}
		).insert(ignore_permissions=True).name

	def _ambiguous_attempt(self, invoice, txn="pi_x", minutes_old=60):
		name = frappe.get_doc(
			{
				"doctype": "Payment Attempt", "invoice": invoice, "team": TEAM, "gateway": GATEWAY,
				"amount": 1000, "currency": "INR", "status": "initiated",
				"gateway_transaction_id": txn,
			}
		).insert(ignore_permissions=True).name
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
		self.assertEqual(a.status, "captured")
		self.assertEqual(a.resolved_by, "reconciliation")

	def test_gateway_failure_fails_attempt_invoice_stays_open(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv)
		with gateway_status("failed"):
			reconciliation.reconcile_attempt(attempt)
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "failed")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_missing_gateway_txn_is_failed_safely(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, txn=None)
		# No gateway call needed when there's no transaction id.
		with gateway_status("succeeded") as adapter:
			reconciliation.reconcile_attempt(attempt)
			adapter.get_transaction_status.assert_not_called()
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "failed")

	def test_pending_recent_is_left_unresolved(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, minutes_old=60)
		with gateway_status("requires_action"):
			out = reconciliation.reconcile_attempt(attempt, now=frappe.utils.now_datetime())
		self.assertEqual(out["unresolved"], "requires_action")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "initiated")

	def test_pending_aged_out_alerts_ops(self):
		inv = self._open_invoice()
		attempt = self._ambiguous_attempt(inv, minutes_old=60)
		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=30)
		with gateway_status("pending"):
			out = reconciliation.reconcile_attempt(attempt, now=future)
		self.assertTrue(out["alerted"])
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv}, pluck="content"
		)
		self.assertTrue(any("Reconciliation" in c for c in comments))


class TestScan(ReconTestBase):
	def test_grace_window_excludes_fresh_attempts(self):
		inv = self._open_invoice()
		fresh = self._ambiguous_attempt(inv, minutes_old=5)  # within 30-min grace
		with gateway_status("succeeded"):
			results = reconciliation.run_reconciliation()
		self.assertNotIn(fresh, [r.get("attempt") for r in results])
		self.assertEqual(frappe.db.get_value("Payment Attempt", fresh, "status"), "initiated")

	def test_scan_resolves_aged_ambiguous(self):
		inv = self._open_invoice()
		old = self._ambiguous_attempt(inv, minutes_old=60)
		with gateway_status("succeeded"):
			reconciliation.run_reconciliation()
		self.assertEqual(frappe.db.get_value("Payment Attempt", old, "status"), "captured")
