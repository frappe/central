# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The sync modes, and an operator sending one record to the accounting system by hand."""

from unittest.mock import patch

import frappe

from central.billing.api.admin import accounting
from central.billing.ingester import advance, customer, erpnext_sync, push
from central.billing.revenue import credits, gst_status
from central.billing.tests.accounting_fake import (
	FakeAccountingSystem,
	billing_team,
	configure_accounting,
	requires_accounting_system,
	sync_mode,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-acct-push"
GSTIN = "27AABCT1111T1Z5"


@requires_accounting_system
class AccountingPushTestCase(IntegrationTestCase):
	def setUp(self):
		configure_accounting()
		self.remote = FakeAccountingSystem()
		self.enterContext(self.remote.patches())
		# The customer module holds its own names for the transport.
		self.enterContext(patch("central.billing.ingester.customer.post", self.remote.post))
		self.put = self.enterContext(patch("central.billing.ingester.customer.put"))
		self.enterContext(patch("central.billing.ingester.customer.has_billable_activity", return_value=True))
		billing_team(TEAM, gstin=GSTIN)

	def _without_customer(self):
		frappe.db.set_value(
			"Billing Profile", TEAM, {"profile_id": None, "address_id": None, "contact_id": None}
		)

	def _top_up(self) -> str:
		return credits.purchase(TEAM, 11800, "INR", gateway_payment_id="pi_push_1", gateway="Stripe")[
			"ledger_entry"
		]

	def _invoice(self, paid_at=None, month=8) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Paid",
					"period_start": f"2026-{month:02d}-01",
					"period_end": str(frappe.utils.get_last_day(f"2026-{month:02d}-01")),
					"currency": "INR",
					"subtotal": 1000,
					"output_tax_amount": 180,
					"total": 1180,
					"credit_applied": 1000,
					"advance_applied": 1000,
					"advance_tax_applied": 180,
					"paid_at": paid_at or frappe.utils.now_datetime(),
					"items": [
						{"plan": "Business VM", "subscription_resource": "vm-1", "rate": 1000, "amount": 1000}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestManualMode(AccountingPushTestCase):
	def test_nothing_is_sent_without_an_operator_but_lookups_run(self):
		self.enterContext(sync_mode("Manual"))
		self._without_customer()
		with patch("frappe.enqueue") as enqueue:
			customer.enqueue_for(TEAM)
			advance.enqueue_sync("any")
			erpnext_sync.enqueue_invoice_sync("any")
			self.assertFalse(customer.awaiting_records(TEAM))  # so issuing is not held
			self.assertEqual(erpnext_sync.retry_failed_syncs(), [])
		enqueue.assert_not_called()
		self.assertTrue(gst_status.lookups_enabled())


class TestPush(AccountingPushTestCase):
	def setUp(self):
		super().setUp()
		self.enterContext(sync_mode("Manual"))
		# A push commits after each step, which ends its locks. A test never commits.
		for path in ("push", "erpnext_sync", "locks"):
			self.enterContext(
				patch(f"central.billing.ingester.{path}.hold_until_transaction_ends", return_value=True)
			)

	def test_an_invoice_is_sent_after_its_customer_and_advances(self):
		self._without_customer()
		entry = self._top_up()
		invoice = self._invoice()

		push.push("Invoice", invoice)

		self.assertEqual(
			[doctype for doctype, _name, _payload in self.remote.posted],
			["Customer", "Address", "Contact", "Payment Entry", "Sales Invoice"],
		)
		self.assertTrue(frappe.db.get_value("Credit Ledger Entry", entry, "advance_id"))
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "erpnext_sync_status"), "Synced")

	def test_a_push_stops_at_the_first_failure_and_keeps_what_was_made(self):
		self._without_customer()
		self._top_up()
		invoice = self._invoice()
		self.remote.fail_on.add("Payment Entry")

		outcome = push.push("Invoice", invoice)

		self.assertTrue(outcome["failed"].startswith("Advance for"))
		self.assertIn("Payment Entry refused", outcome["error"])
		self.assertNotIn("Sales Invoice", [doctype for doctype, _name, _payload in self.remote.posted])
		self.assertTrue(frappe.db.get_value("Billing Profile", TEAM, "contact_id"))

	def test_a_preview_sends_and_records_nothing(self):
		self._without_customer()
		invoice = self._invoice()
		self._top_up()

		with patch("central.billing.ingester.erpnext_sync._advances", return_value=[]):
			sent = push.preview("Invoice", invoice)

		self.assertEqual(sent["Sales Invoice"]["customer"], push.NEW_CUSTOMER)
		self.assertEqual(self.remote.posted, [])
		self.assertFalse(frappe.db.get_value("Invoice", invoice, "gst_state_recorded"))

	def test_only_an_operator_may_push(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			accounting.send_to_accounting("Invoice", self._invoice())
		self.assertEqual(self.remote.posted, [])


class TestNeverSent(AccountingPushTestCase):
	def test_automatic_mode_sends_paid_invoices_no_sync_tried(self):
		now = frappe.utils.now_datetime()
		old = self._invoice(paid_at=frappe.utils.add_to_date(now, hours=-2))
		just_paid = self._invoice(paid_at=now, month=9)  # its own job is queued

		never_sent = erpnext_sync._never_sent(now)

		self.assertIn(old, never_sent)
		self.assertNotIn(just_paid, never_sent)
