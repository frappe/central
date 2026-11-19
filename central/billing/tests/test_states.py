# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The single transition authority + the derived Billing Event stream (ADR 0016)."""

import frappe

from central.billing import states
from central.billing.revenue import invoicing
from central.billing.states import InvalidTransition, transition
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, make_billing_subscription, make_plan

TEAM = "team-states"
CLUSTER = "ap-south-1"
PLAN = "bundle-states-test"


class TestInvoiceStateMachine(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		self.inv = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Billing Event", {"team": TEAM})
		for dt in ("Invoice", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _events(self):
		return frappe.get_all(
			"Billing Event",
			filters={"subject_doctype": "Invoice", "subject": self.inv},
			fields=["from_state", "to_state", "actor", "reason", "correlation", "event_type"],
			order_by="occurred_at asc, creation asc",
		)

	def test_a_legal_move_writes_the_field_and_appends_one_event(self):
		doc = frappe.get_doc("Invoice", self.inv)
		transition(doc, "Overdue", reason="overdue", actor="scheduler")

		self.assertEqual(doc.status, "Overdue")  # field written on the in-memory doc
		events = self._events()
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].from_state, "Outstanding")
		self.assertEqual(events[0].to_state, "Overdue")
		self.assertEqual(events[0].actor, "scheduler")
		self.assertEqual(events[0].reason, "overdue")
		# Correlation defaults to the invoice's own name, so its events thread together.
		self.assertEqual(events[0].correlation, self.inv)
		self.assertEqual(events[0].event_type, "Invoice Overdue")

	def test_an_illegal_move_is_refused_and_records_nothing(self):
		doc = frappe.get_doc("Invoice", self.inv)
		transition(doc, "Paid", reason="credits")  # Outstanding → Paid is legal
		self.assertEqual(len(self._events()), 1)

		# Paid is terminal: reopening it is impossible, and the refusal leaves no trace.
		with self.assertRaises(InvalidTransition):
			transition(doc, "Outstanding")
		self.assertEqual(doc.status, "Paid")  # unchanged
		self.assertEqual(len(self._events()), 1)  # no event for the rejected move

	def test_paying_a_cancelled_invoice_is_impossible(self):
		doc = frappe.get_doc("Invoice", self.inv)
		transition(doc, "Cancelled", reason="superseded")
		with self.assertRaises(InvalidTransition):
			transition(doc, "Paid")

	def test_open_and_collect_records_that_collection_began(self):
		invoicing.open_and_collect(self.inv, collect=False)

		self.assertTrue(frappe.db.get_value("Invoice", self.inv, "due_date"))
		self.assertIn("Invoice Issued", [e.event_type for e in self._events()])


class TestDeclaredMachines(IntegrationTestCase):
	"""The legal edges each machine declares — locked down so a refactor can't quietly
	widen a machine (e.g. let a refunded attempt be re-captured, or an invoice reopen)."""

	def test_invoice_edges(self):
		self.assertTrue(states.INVOICE.allows("Outstanding", "Paid"))
		self.assertFalse(states.INVOICE.allows("Paid", "Outstanding"))  # terminal
		self.assertFalse(states.INVOICE.allows("Cancelled", "Paid"))  # can't pay a cancel

	def test_payment_attempt_edges(self):
		self.assertTrue(states.PAYMENT_ATTEMPT.allows("Initiated", "Captured"))
		self.assertTrue(states.PAYMENT_ATTEMPT.allows("Captured", "Refunded"))
		self.assertTrue(states.PAYMENT_ATTEMPT.allows("Captured", "Failed"))  # failure webhook races capture
		self.assertFalse(states.PAYMENT_ATTEMPT.allows("Refunded", "Captured"))
		self.assertFalse(states.PAYMENT_ATTEMPT.allows("Failed", "Captured"))

	def test_standing_edges(self):
		self.assertTrue(states.SUBSCRIPTION_STANDING.allows("Current", "Past Due"))
		self.assertTrue(states.SUBSCRIPTION_STANDING.allows("Past Due", "Suspended"))
		self.assertFalse(states.SUBSCRIPTION_STANDING.allows("Current", "Suspended"))  # grace step

	def test_refund_edges(self):
		self.assertTrue(states.REFUND.allows("Initiated", "Completed"))
		self.assertTrue(states.REFUND.allows("Initiated", "Failed"))
		self.assertFalse(states.REFUND.allows("Completed", "Failed"))

	def test_payment_method_edges(self):
		self.assertTrue(states.PAYMENT_METHOD.allows("Pending Validation", "Active"))
		self.assertTrue(states.PAYMENT_METHOD.allows("Pending Validation", "Cancelled"))  # abandoned
		self.assertTrue(states.PAYMENT_METHOD.allows("Active", "Expired"))
		self.assertTrue(states.PAYMENT_METHOD.allows("Active", "Cancelled"))
		self.assertFalse(states.PAYMENT_METHOD.allows("Cancelled", "Active"))  # terminal
		self.assertFalse(states.PAYMENT_METHOD.allows("Expired", "Active"))  # terminal

	def test_webhook_event_edges(self):
		self.assertTrue(states.WEBHOOK_EVENT.allows("Received", "Processed"))
		self.assertTrue(states.WEBHOOK_EVENT.allows("Received", "Ignored"))
		self.assertFalse(states.WEBHOOK_EVENT.allows("Processed", "Ignored"))
