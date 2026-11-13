# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Every customer-visible amount names the GST it includes (#193 part B)."""

from unittest.mock import patch

import frappe

from central.billing.api.dashboard import invoices as invoice_api
from central.billing.api.dashboard import outlook
from central.billing.revenue import credits, tax
from central.billing.revenue.invoicing import wallet_draw
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-tax-labels"
# The company is in Maharashtra (27).
COMPANY_STATE = "27"


def _set_gst(team: str, **kw) -> None:
	frappe.db.delete("Tax Profile", {"team": team})
	frappe.get_doc(
		{"doctype": "Tax Profile", "team": team, "output_tax_type": "GST", "output_tax_rate": 18, **kw}
	).insert(ignore_permissions=True)


def _invoice(team: str, subtotal=10000, rate=18, sez=False, **kw) -> str:
	"""An open INR invoice, taxed at `rate` unless zero-rated to an SEZ."""
	gst = 0 if sez else frappe.utils.flt(subtotal * rate / 100, 2)
	total = subtotal + gst
	return (
		frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": team,
				"invoice_type": "Billable",
				"status": "Outstanding",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
				"payment_date": "2026-11-05",
				"due_date": "2026-11-05",
				"suspends_on": "2026-12-15",
				"currency": "INR",
				"subtotal": subtotal,
				"output_tax_type": "GST",
				"output_tax_rate": rate,
				"output_tax_amount": gst,
				"zero_rating_reason": "SEZ" if sez else None,
				"total": total,
				"expected_collection": total,
				"items": [
					{"resource_type": "bundle", "plan": "p", "rate": subtotal, "days": 31, "amount": subtotal}
				],
				**kw,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TaxLabelTestCase(IntegrationTestCase):
	team = TEAM

	def setUp(self):
		ensure_team(self.team)
		complete_billing_profile(self.team)
		_set_gst(self.team)
		frappe.db.delete("Billing Notification Log", {"team": self.team})
		self.enterContext(
			patch("central.billing.ingester.gst.cached_company_state_code", return_value=COMPANY_STATE)
		)

	def tearDown(self):
		for doctype in ("Tax Profile", "Billing Notification Log", "Team Notification"):
			frappe.db.delete(doctype, {"team": self.team})

	def _move_to(self, state: str) -> None:
		frappe.db.set_value("Billing Profile", self.team, "state", state)


class TestInvoiceKeepsItsTax(TaxLabelTestCase):
	def test_an_igst_invoice_is_named_igst(self):
		self._move_to("Karnataka")
		doc = frappe.get_doc("Invoice", _invoice(TEAM))
		self.assertEqual(tax.TaxNames(TEAM).label(doc), "IGST 18%")
		self.assertEqual(tax.TaxNames(TEAM).note(doc), "incl. IGST 18%")

	def test_an_in_state_invoice_is_named_cgst_and_sgst(self):
		doc = frappe.get_doc("Invoice", _invoice(TEAM))
		self.assertEqual(tax.TaxNames(TEAM).note(doc), "incl. CGST 9% + SGST 9%")

	def test_an_invoice_keeps_the_rate_it_was_issued_with(self):
		self._move_to("Karnataka")
		doc = frappe.get_doc("Invoice", _invoice(TEAM, rate=12))
		self.assertEqual(tax.TaxNames(TEAM).label(doc), "IGST 12%")

	def test_an_sez_invoice_stays_zero_rated_after_the_profile_changes(self):
		doc = frappe.get_doc("Invoice", _invoice(TEAM, sez=True))
		self.assertEqual(tax.TaxNames(TEAM).note(doc), "No GST (SEZ)")
		self.assertIn("Special Economic Zone", tax.TaxNames.reason(doc))

	def test_an_untaxed_invoice_names_nothing(self):
		doc = frappe.get_doc("Invoice", _invoice(TEAM, rate=0))
		self.assertIsNone(tax.TaxNames(TEAM).note(doc))


class TestApisExposeTheLabel(TaxLabelTestCase):
	def test_the_invoice_detail_names_its_tax_and_reason(self):
		self._move_to("Karnataka")
		igst = invoice_api.get_invoice(_invoice(TEAM))
		sez = invoice_api.get_invoice(_invoice(TEAM, sez=True, period_start="2026-09-01"))

		self.assertEqual(igst["tax_label"], "IGST 18%")
		self.assertIsNone(igst["tax_reason"])
		self.assertEqual(sez["tax_label"], "No GST (SEZ)")
		self.assertIn("Special Economic Zone", sez["tax_reason"])

	def test_the_invoice_list_says_what_each_total_includes(self):
		name = _invoice(TEAM)
		row = next(r for r in invoice_api.list_invoices(TEAM) if r["name"] == name)
		self.assertEqual(row["tax_note"], "incl. CGST 9% + SGST 9%")

	def test_the_next_payment_says_what_it_includes(self):
		self._move_to("Karnataka")
		_invoice(TEAM)
		self.assertEqual(outlook.get_next_payment(TEAM)["tax_note"], "incl. IGST 18%")

	def test_the_wallet_history_names_the_gst_of_a_top_up(self):
		with patch("central.billing.ingester.advance.enqueue_sync"):
			credits.purchase(TEAM, 1180, "INR", gateway_payment_id="pay_tax_labels", gateway="razorpay")
		self._move_to("Karnataka")
		rows = invoice_api.credit_ledger(TEAM)
		self.assertEqual(rows[0]["tax_label"], "IGST 18%")
		self.assertEqual(rows[0]["tax_amount"], 180)


class TestSpendLimitIsBeforeTax(TaxLabelTestCase):
	def test_spend_history_carries_spend_before_tax(self):
		from central.billing.api.dashboard import reports

		with self.freeze_time("2026-11-13 10:00:00"):
			_invoice(TEAM)
			october = next(m for m in reports.get_spend_history(TEAM)["months"] if m["month"] == "2026-10")

		self.assertEqual(october["subtotal"], 10000)
		self.assertEqual(october["total"], 11800)


class TestShortfallCountsTopUpGst(TaxLabelTestCase):
	def test_gst_paid_with_top_ups_pays_the_bill_gst(self):
		"""₹10,000 of top-ups with ₹1,800 GST paid on them pays a ₹11,800 bill outright."""
		with patch("central.billing.ingester.advance.enqueue_sync"):
			credits.purchase(TEAM, 11800, "INR", gateway_payment_id="pay_tax_labels_gst", gateway="razorpay")

		self.assertEqual(credits.get_balance(TEAM)["balance"], 10000)
		self.assertEqual(wallet_draw.get_wallet_shortfall(TEAM, "INR", 11800, 1800), 0)

	def test_promotional_credit_pays_the_bill_with_its_gst(self):
		credits.grant_promotional_credits(TEAM, 10000, "INR")
		self.assertEqual(wallet_draw.get_wallet_shortfall(TEAM, "INR", 11800, 1800), 1800)
