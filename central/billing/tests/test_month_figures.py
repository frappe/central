# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, today

from central.billing.report import _month_figures
from central.billing.report._inventory import Inventory
from central.billing.revenue import credits
from central.billing.tests.test_unit_economics import REGION, seed_fleet
from central.billing.tests.utils import BillingTestCase, complete_billing_profile, ensure_team

PAYER = "team-figures-payer"
OURS = "team-figures-ours"
MONTH = "2026-10-01"


def invoice(team, amount, status="Paid", **values):
	frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": team,
			"invoice_type": "Billable",
			"status": status,
			"period_start": MONTH,
			"period_end": "2026-10-31",
			"currency": "INR",
			"subtotal": amount,
			"total": amount,
			"items": [{"resource_type": "bundle", "amount": amount}],
			**values,
		}
	).insert(ignore_permissions=True)


class TestMonthFigures(BillingTestCase):
	def test_the_month_splits_into_cash_free_credit_and_waived(self):
		for team in (PAYER, OURS):
			ensure_team(team)
			complete_billing_profile(team)
		frappe.db.set_value("Billing Profile", OURS, {"is_internal": 1, "internal_reason": "Ours"})
		invoice(PAYER, 1000, amount_paid=700, credit_applied=300)
		invoice(OURS, 500, status="Waived")

		figures = _month_figures.month_figures(MONTH)

		headline = figures["headline"]
		self.assertEqual(headline["billed"], 1000)
		self.assertEqual((headline["cash_collected"], headline["paid_by_free_credit"]), (700, 300))
		self.assertEqual(headline["waived"], 500)
		self.assertEqual((figures["customers"]["paying"], figures["customers"]["first_payments"]), (1, 1))
		self.assertEqual(figures["services"]["bundled"]["revenue"], 1000)
		self.assertEqual(figures["services"]["unbundled"]["revenue"], 0)

	def test_credit_left_splits_into_bought_and_free_by_expiry(self):
		ensure_team(PAYER)
		complete_billing_profile(PAYER)
		credits._book_entry(PAYER, "Credit", 500, "INR", reference_type="Top-up", extra={"paid_in": 1})
		credits.grant_promotional_credits(PAYER, 300, "INR", expires_on=add_days(today(), 20))
		credits.grant_promotional_credits(PAYER, 200, "INR", expires_on=add_days(today(), 50))

		figures = _month_figures.credit(set())

		self.assertEqual((figures["bought_left"], figures["free_left"]), (500, 500))
		self.assertEqual(figures["free_expiring_in_30_days"], 300)
		self.assertEqual(figures["free_expiring_in_60_days"], 500)
		self.assertEqual(figures["teams_on_free_credit"], 1)

	def test_the_margin_at_list_price_and_the_actual_margin_both_carry_the_metal_bill(self):
		seed_fleet()

		figures = _month_figures.margins(Inventory({"region": REGION}))

		self.assertEqual((figures["metal_cost"], figures["idle_cost"]), (40000, 36000))
		self.assertEqual((figures["list_value"], figures["revenue"]), (5000, 3000))
		self.assertEqual((figures["margin_at_list"], figures["actual_margin"]), (-35000, -37000))
		self.assertEqual(figures["by_funding"]["Not Paying Yet"]["list_value"], 1000)
