# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.report.billing_lookup import billing_lookup
from central.billing.states import record_team_event
from central.billing.tests.utils import BillingTestCase, complete_billing_profile, ensure_team, make_user

TEAM = "team-billing-lookup"


class TestBillingLookupReport(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_only_an_operator_can_run_it(self):
		frappe.set_user(make_user())
		with self.assertRaises(frappe.PermissionError):
			billing_lookup.execute({"team": TEAM})

	def test_an_incomplete_profile_is_red_and_names_what_is_missing(self):
		frappe.db.delete("Billing Profile", {"team": TEAM})
		card = self._card("Billing Profile")
		self.assertEqual(card["indicator"], "red")
		self.assertIn("city", card["value"])

	def test_a_failed_method_is_listed_with_its_reason_and_counted(self):
		complete_billing_profile(TEAM)
		self._method(status="Failed", failure_reason="Card declined by the bank")
		self._method(status="Cancelled", failure_reason="Removed")
		_columns, rows, *_ = billing_lookup.execute({"team": TEAM, "view": billing_lookup.METHODS})
		self.assertEqual([r.failure_reason for r in rows], ["Card declined by the bank"])
		self.assertEqual(self._card("Methods That Cannot Be Charged")["value"], 1)

	def test_a_held_draft_is_held_not_owed(self):
		complete_billing_profile(TEAM)
		self._invoice("Outstanding", hold_reason="GSTIN Check")
		self._invoice("Overdue", due_date="2099-01-10", period_start="2098-12-01", period_end="2098-12-31")
		self._invoice("Paid", period_start="2098-11-01", period_end="2098-11-30")
		_columns, rows, *_ = billing_lookup.execute({"team": TEAM, "view": billing_lookup.INVOICES})
		self.assertEqual(len(rows), 2)
		self.assertEqual(self._card("Held Invoices")["value"], 1)
		owed = self._card("Owed (INR)")
		self.assertEqual((owed["value"], owed["indicator"]), (100, "red"))

	def test_events_stop_at_the_latest_twenty(self):
		for n in range(22):
			record_team_event(TEAM, "Invoice Failed", "Invoice", reason=f"run {n}", outcome="Failed")
		_columns, rows, *_ = billing_lookup.execute({"team": TEAM})
		self.assertEqual(len(rows), billing_lookup.EVENT_LIMIT)

	def _card(self, label):
		summary = billing_lookup.execute({"team": TEAM})[4]
		return next(card for card in summary if card["label"] == label)

	def _method(self, **values):
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": "Stripe",
				"method_type": "Card",
				"gateway_method_id": f"pm_{frappe.generate_hash(8)}",
				"gateway_customer_id": f"cus_{TEAM}",
				**values,
			}
		).insert(ignore_permissions=True)

	def _invoice(self, status, **values):
		frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": status,
				"period_start": "2099-01-01",
				"period_end": "2099-01-31",
				"currency": "INR",
				"subtotal": 100,
				"total": 100,
				"amount_paid": 100 if status == "Paid" else 0,
				**values,
			}
		).insert(ignore_permissions=True)
