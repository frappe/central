# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""ERPNext async Sales Invoice sync (issue #17)."""

from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.billing.revenue import erpnext_sync

TEAM = "team-erp"


def ok_response(name="SINV-2026-001"):
	resp = MagicMock()
	resp.raise_for_status.return_value = None
	resp.json.return_value = {"data": {"name": name}}
	return resp


def err_response():
	resp = MagicMock()
	resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
	return resp


class ErpnextSyncTestBase(IntegrationTestCase):
	def setUp(self):
		frappe.conf.erpnext_url = "https://erp.example"
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.commit()

	def _paid_invoice(self, status="Paid", invoice_type="billable"):
		return frappe.get_doc(
			{
				"doctype": "Invoice", "team": TEAM, "invoice_type": invoice_type, "status": status,
				"period_start": "2026-05-01", "period_end": "2026-05-31", "currency": "INR",
				"subtotal": 1000, "total": 1180, "expected_collection": 1180, "amount_paid": 1180,
				"items": [
					{"subscription_resource": "srv-1", "plan": "bundle-2vcpu", "resource_type": "bundle",
					 "rate": 1000, "days": 30, "amount": 1000},
				],
			}
		).insert(ignore_permissions=True).name


class TestSyncSuccess(ErpnextSyncTestBase):
	def test_paid_invoice_syncs_and_stores_reference(self):
		inv = self._paid_invoice()
		with patch("central.billing.revenue.erpnext_sync.requests.post", return_value=ok_response("SINV-9")) as post:
			out = erpnext_sync.sync_invoice(inv)

		self.assertEqual(out["synced"], "SINV-9")
		doc = frappe.get_doc("Invoice", inv)
		self.assertEqual(doc.erpnext_invoice, "SINV-9")
		self.assertEqual(doc.erpnext_sync_status, "synced")
		# Payload carries the Sales Invoice shape + a back-reference.
		payload = post.call_args.kwargs["json"]
		self.assertEqual(payload["doctype"], "Sales Invoice")
		self.assertEqual(payload["cloud_billing_invoice"], inv)
		self.assertEqual(len(payload["items"]), 1)

	def test_already_synced_is_idempotent(self):
		inv = self._paid_invoice()
		frappe.db.set_value("Invoice", inv, {"erpnext_invoice": "SINV-1", "erpnext_sync_status": "synced"})
		with patch("central.billing.revenue.erpnext_sync.requests.post") as post:
			out = erpnext_sync.sync_invoice(inv)
			post.assert_not_called()
		self.assertEqual(out["skipped"], "already_synced")

	def test_cost_report_and_unpaid_are_skipped(self):
		cost = self._paid_invoice(invoice_type="cost_report")
		draft = self._paid_invoice(status="Open")
		with patch("central.billing.revenue.erpnext_sync.requests.post") as post:
			self.assertEqual(erpnext_sync.sync_invoice(cost)["skipped"], "not_billable")
			self.assertEqual(erpnext_sync.sync_invoice(draft)["skipped"], "not_paid")
			post.assert_not_called()


class TestFailureIsolation(ErpnextSyncTestBase):
	def test_erpnext_500_does_not_touch_the_customer_invoice(self):
		inv = self._paid_invoice()
		with patch("central.billing.revenue.erpnext_sync.requests.post", return_value=err_response()):
			out = erpnext_sync.sync_invoice(inv)

		self.assertTrue(out["retry_scheduled"])
		doc = frappe.get_doc("Invoice", inv)
		self.assertEqual(doc.status, "Paid")  # never rolled back
		self.assertEqual(doc.erpnext_sync_status, "pending")
		self.assertEqual(doc.erpnext_sync_attempts, 1)
		self.assertTrue(doc.erpnext_next_retry_at)  # backoff scheduled
		self.assertFalse(doc.erpnext_invoice)

	def test_backoff_grows_then_alerts_ops_after_three_attempts(self):
		inv = self._paid_invoice()
		with patch("central.billing.revenue.erpnext_sync.requests.post", return_value=err_response()):
			a1 = erpnext_sync.sync_invoice(inv)
			a2 = erpnext_sync.sync_invoice(inv)
			a3 = erpnext_sync.sync_invoice(inv)

		self.assertEqual(a1["backoff_seconds"], 60)
		self.assertEqual(a2["backoff_seconds"], 120)  # exponential
		self.assertEqual(a3.get("failed") is not None, True)
		doc = frappe.get_doc("Invoice", inv)
		self.assertEqual(doc.status, "Paid")
		self.assertEqual(doc.erpnext_sync_status, "failed")
		self.assertEqual(doc.erpnext_sync_attempts, 3)
		# Ops alerted (not the customer).
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv, "comment_type": "Info"},
			pluck="content",
		)
		self.assertTrue(any("ERPNext sync failed" in c for c in comments))

	def test_retry_scheduler_picks_up_due_pending_and_succeeds(self):
		inv = self._paid_invoice()
		with patch("central.billing.revenue.erpnext_sync.requests.post", return_value=err_response()):
			erpnext_sync.sync_invoice(inv)  # → pending, next_retry_at in ~60s

		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=120)
		with patch("central.billing.revenue.erpnext_sync.requests.post", return_value=ok_response("SINV-RETRY")):
			erpnext_sync.retry_failed_syncs(now=future)

		doc = frappe.get_doc("Invoice", inv)
		self.assertEqual(doc.erpnext_sync_status, "synced")
		self.assertEqual(doc.erpnext_invoice, "SINV-RETRY")


class TestPostPaymentHook(ErpnextSyncTestBase):
	def test_enqueue_after_commit(self):
		inv = self._paid_invoice()
		with patch("central.billing.revenue.erpnext_sync.frappe.enqueue") as enqueue:
			erpnext_sync.enqueue_invoice_sync(inv)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["invoice"], inv)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
