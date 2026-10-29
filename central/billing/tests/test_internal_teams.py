# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An internal team's invoices are rated for the record and waived, never collected."""

from unittest.mock import patch

import frappe

from central.billing.ingester import customer
from central.billing.report.internal_usage_and_waivers import internal_usage_and_waivers as report
from central.billing.revenue import credits, invoicing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, make_billing_subscription, make_plan

TEAM = "team-internal-waiver"
CLUSTER = "ap-south-1"
PLAN = "bundle-internal-waiver"


def _mark_internal(reason="Platform team's own servers"):
	values = {"doctype": "Tax Profile", "team": TEAM, "output_tax_type": "GST", "output_tax_rate": 18}
	doc = (
		frappe.get_doc("Tax Profile", TEAM)
		if frappe.db.exists("Tax Profile", TEAM)
		else frappe.get_doc(values)
	)
	doc.is_internal = 1
	doc.internal_reason = reason
	doc.save(ignore_permissions=True)
	return doc


class TestInternalTeams(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.delete("Tax Profile", {"team": TEAM})
		frappe.db.delete("Billing Event", {"team": TEAM})
		self.invoice = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")

	def test_marking_internal_needs_a_reason(self):
		with self.assertRaises(frappe.ValidationError):
			_mark_internal(reason="")

	def test_marking_internal_is_logged(self):
		_mark_internal()
		events = frappe.get_all("Billing Event", filters={"team": TEAM}, pluck="event_type")
		self.assertEqual(events, ["Internal Team Marked"])

	def test_invoice_is_waived_untaxed_without_drawing_credits(self):
		_mark_internal()
		credits.grant_promotional_credits(TEAM, 500, "INR", note="Welcome credits")

		result = invoicing.open_and_collect(self.invoice)

		invoice = frappe.get_doc("Invoice", self.invoice)
		self.assertEqual(result["status"], "Waived")
		self.assertEqual(
			(invoice.status, invoice.output_tax_amount, invoice.credit_applied), ("Waived", 0, 0)
		)
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 500)

	def test_internal_team_is_not_sent_to_accounting(self):
		_mark_internal()
		profile = frappe._dict(
			team=TEAM, currency="INR", legal_name="Us", address_line1="1", city="Pune", country="India"
		)
		self.assertFalse(customer._should_sync(profile))

	def test_report_shows_usage_and_waived_amount(self):
		_mark_internal()
		invoicing.open_and_collect(self.invoice)

		_, rows, _ = report.execute({"team": TEAM})

		self.assertEqual([(r["invoice"], r["waived"]) for r in rows], [(self.invoice, 1000)])

	def test_marking_internal_waives_unpaid_invoices_only(self):
		credits.grant_promotional_credits(TEAM, 2000, "INR", note="Welcome credits")
		invoicing.open_and_collect(self.invoice, collect=False)  # credits pay it in full
		open_invoice = self._open_invoice()

		_mark_internal()

		self.assertEqual(frappe.db.get_value("Invoice", open_invoice, "status"), "Waived")
		self.assertEqual(frappe.db.get_value("Invoice", self.invoice, "status"), "Paid")

	def test_an_internal_team_is_not_dunned_or_charged(self):
		from central.billing.payments import collection
		from central.billing.revenue import dunning

		open_invoice = self._open_invoice()
		self._payment_attempt(open_invoice)
		_mark_internal()  # the invoice with a payment under way stays Open

		self.assertNotIn(open_invoice, [r.get("invoice") for r in dunning.run_dunning()])
		self.assertEqual(collection.collect_invoice(open_invoice)["reason"], "internal_team")

	def test_dunning_settles_internal_teams_first(self):
		from central.billing.revenue import dunning

		open_invoice = self._open_invoice()
		_mark_internal()
		frappe.db.set_value("Invoice", open_invoice, "status", "Overdue")  # missed by the mark-time waive

		dunning.run_dunning()

		self.assertEqual(frappe.db.get_value("Invoice", open_invoice, "status"), "Waived")

	def test_the_monthly_draft_tick_settles_internal_teams_first(self):
		from central.billing.revenue.invoicing import run

		open_invoice = self._open_invoice()
		_mark_internal()
		frappe.db.set_value("Invoice", open_invoice, "status", "Overdue")  # missed by the mark-time waive

		with patch("frappe.enqueue"):
			run.draft_monthly_invoices()

		self.assertEqual(frappe.db.get_value("Invoice", open_invoice, "status"), "Waived")

	def test_payment_claimed_before_the_lock_is_not_waived(self):
		open_invoice = self._open_invoice()
		get_doc, raced = frappe.get_doc, []

		def collector_wins_the_race(*args, **kwargs):
			# A collector claims an attempt after the invoice was listed, before it was locked.
			if args[:2] == ("Invoice", open_invoice) and kwargs.get("for_update") and not raced:
				raced.append(self._payment_attempt(open_invoice))
			return get_doc(*args, **kwargs)

		with patch.object(frappe, "get_doc", side_effect=collector_wins_the_race):
			_mark_internal()

		self.assertEqual(frappe.db.get_value("Invoice", open_invoice, "status"), "Open")

	def _payment_attempt(self, invoice):
		return frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": invoice,
				"team": TEAM,
				"gateway": "Stripe",
				"amount": 100,
				"currency": "INR",
				"status": "Initiated",
			}
		).insert(ignore_permissions=True)

	def _open_invoice(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-07-01",
					"period_end": "2026-07-31",
					"currency": "INR",
					"subtotal": 100,
					"total": 100,
					"expected_collection": 100,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
