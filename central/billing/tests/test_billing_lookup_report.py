# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.report.billing_lookup import billing_lookup
from central.billing.states import record_team_event
from central.billing.tests.utils import (
	BillingTestCase,
	add_segment,
	complete_billing_profile,
	ensure_team,
	make_plan,
	make_user,
	seed_running_resource,
)

TEAM = "team-billing-lookup"
PLAN = "bundle-billing-lookup"


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

	def test_an_event_says_what_happened_to_its_money(self):
		record_team_event(TEAM, "Invoice Paid", "Invoice", amount=500, outcome="Success")
		record_team_event(TEAM, "Invoice Credited Somewhere", "Invoice", amount=10, outcome="Success")
		record_team_event(TEAM, "Subscription Created", "Subscription", outcome="Success")
		rows = {r.event_type: r for r in self._rows(billing_lookup.EVENTS)}
		self.assertEqual(rows["Invoice Paid"].money_meaning, "Paid to us")
		self.assertTrue(rows["Invoice Credited Somewhere"].money_unexplained)
		self.assertIsNone(rows["Subscription Created"].amount)
		self.assertIsNone(rows["Subscription Created"].money_meaning)

	def test_subscriptions_show_their_monthly_cost_and_a_total(self):
		make_plan(PLAN)
		seed_running_resource(TEAM, "srv-lookup-a", "ap-south-1", PLAN, rate=1000)
		seed_running_resource(TEAM, "srv-lookup-b", "ap-south-1", PLAN, rate=2500)
		rows = self._rows(billing_lookup.SUBSCRIPTIONS)
		self.assertEqual(sorted(r["monthly_cost"] for r in rows if not r.get("is_total")), [1000, 2500])
		self.assertEqual([r["monthly_cost"] for r in rows if r.get("is_total")], [3500])
		self.assertEqual(self._card("Monthly Cost (INR)")["value"], 3500)

	def test_a_plan_change_is_named_an_upgrade_or_a_downgrade(self):
		make_plan(PLAN)
		sub = seed_running_resource(TEAM, "srv-lookup-c", "ap-south-1", PLAN, rate=1000)
		add_segment(sub, "Plan Changed", 1800, "2026-07-01 00:00:00", plan=PLAN)
		add_segment(sub, "Plan Changed", 1200, "2026-08-01 00:00:00", plan=PLAN)
		add_segment(sub, "Cancelled", 0, "2026-09-01 00:00:00")
		rows = self._rows(billing_lookup.CHANGES)
		self.assertEqual(
			[(r.effect, r.cost_change) for r in rows],
			[("Billing stopped", -1200), ("Downgrade", -600), ("Upgrade", 800), ("Billing started", 1000)],
		)

	def _rows(self, view):
		return billing_lookup.execute({"team": TEAM, "view": view})[1]

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
