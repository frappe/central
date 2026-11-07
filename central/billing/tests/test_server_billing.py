# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
import inspect

import frappe

from central.billing.api import billing_api, server_billing
from central.billing.tests.utils import (
	BillingTestCase,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	seed_running_resource,
)

PLAN = "bundle-server-billing"
TEAM = "team-server-billing"
CLUSTER = "ap-south-1"
OWN = "srv-billing-own"
OTHER = "srv-billing-other"


class TestServerBilling(BillingTestCase):
	"""In-app billing for one server: its share of the next bill and of each team invoice, and
	the invoice PDF only when the invoice covers that server alone."""

	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		frappe.db.delete("Invoice", {"team": TEAM})
		for server in (OWN, OTHER):
			if not frappe.db.exists("Virtual Machine", server):
				seed_running_resource(TEAM, server, CLUSTER, PLAN)
		frappe.local.pilot_credential = frappe._dict(team=TEAM, server=OWN)

	def _invoice(self, amounts: dict, status="Paid", sales_invoice=None) -> str:
		subtotal = sum(amounts.values())
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": status,
					"period_start": "2099-01-01",
					"period_end": "2099-01-31",
					"currency": "INR",
					"subtotal": subtotal,
					"output_tax_type": "GST",
					"output_tax_amount": subtotal * 0.18,
					"total": subtotal * 1.18,
					"erpnext_invoice": sales_invoice,
					"items": [
						{
							"resource_type": "bundle",
							"plan": PLAN,
							"subscription_resource": server,
							"amount": amount,
						}
						for server, amount in amounts.items()
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_shared_invoice_shows_this_servers_share_with_its_tax(self):
		self._invoice({OWN: 1000, OTHER: 3000}, status="Outstanding", sales_invoice="SINV-1")

		[statement] = server_billing.get_server_invoices(TEAM, OWN)

		self.assertEqual(statement["amount"], frappe.utils.fmt_money(1180, currency="INR"))
		self.assertFalse(statement["has_pdf"])
		self.assertFalse(statement["can_pay"])

	def test_an_invoice_for_this_server_alone_offers_its_pdf_and_payment(self):
		self._invoice({OWN: 1000}, status="Outstanding", sales_invoice="SINV-2")

		[statement] = server_billing.get_server_invoices(TEAM, OWN)

		self.assertTrue(statement["has_pdf"])
		self.assertTrue(statement["can_pay"])

	def test_an_invoice_without_this_server_is_left_out(self):
		self._invoice({OTHER: 3000})

		self.assertEqual(server_billing.get_server_invoices(TEAM, OWN), [])

	def test_the_pdf_of_an_invoice_that_covers_another_server_is_refused(self):
		invoice = self._invoice({OWN: 1000, OTHER: 3000}, sales_invoice="SINV-3")

		with self.assertRaises(frappe.PermissionError):
			inspect.unwrap(billing_api.get_server_invoice_pdf)(invoice=invoice)

	def test_the_next_bill_counts_only_this_servers_lines_and_its_tax_share(self):
		forecast = {
			"subtotal": 4000,
			"tax_amount": 720,
			"tax_type": "GST",
			"days_remaining": 12,
			"line_items": [
				{"subscription_resource": OWN, "item": "Starter", "detail": None, "amount": 1000},
				{"subscription_resource": OTHER, "item": "Pro", "detail": None, "amount": 3000},
			],
		}

		bill = server_billing.get_next_bill(TEAM, OWN, forecast, "INR")

		self.assertEqual(bill["amount"], frappe.utils.fmt_money(1180, currency="INR"))
		self.assertEqual(bill["tax"], frappe.utils.fmt_money(180, currency="INR"))
		self.assertEqual([line["item"] for line in bill["lines"]], ["Starter"])
