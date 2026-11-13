# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An issued invoice keeps the GST split it was charged and filed with."""

from unittest.mock import patch

import frappe
from frappe.utils import getdate

from central.billing.doctype.invoice.invoice import period_key_for
from central.billing.ingester import erpnext_sync, gst
from central.billing.revenue import invoicing
from central.billing.tests.accounting_fake import IN_STATE, OUT_STATE, billing_team
from central.billing.tests.test_erpnext_sync import SyncTestCase
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_team,
	make_billing_subscription,
	make_plan,
)
from central.patches.v0_0 import record_gst_split_on_issued_invoices

TEAM = "team-gst-split"
OTHER_TEAM = "team-gst-split-other"
PLAN = "bundle-gst-split"
COMPANY_STATE = "central.billing.ingester.gst.cached_company_state_code"


def _set_gst(team, **kw):
	frappe.db.delete("Tax Profile", {"team": team})
	frappe.get_doc({"doctype": "Tax Profile", "team": team, **kw}).insert(ignore_permissions=True)


class TestSplitAtIssue(IntegrationTestCase):
	"""The company is in Maharashtra (27)."""

	def setUp(self):
		make_plan(PLAN)
		sub = make_billing_subscription(TEAM, "ap-south-1", PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		complete_billing_profile(TEAM)
		_set_gst(TEAM, output_tax_type="GST", output_tax_rate=18)
		self.invoice = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")

	def _issue(self, company_state="27"):
		with patch(COMPANY_STATE, return_value=company_state):
			invoicing.open_and_collect(self.invoice, collect=False)
		return frappe.db.get_value("Invoice", self.invoice, ["output_tax_amount", "gst_split"])

	def test_same_state_is_cgst_and_sgst(self):
		self.assertEqual(self._issue(), (180, "CGST + SGST"))

	def test_another_state_is_igst(self):
		frappe.db.set_value("Billing Profile", TEAM, "state", "Karnataka")
		self.assertEqual(self._issue(), (180, "IGST"))

	def test_no_state_is_igst(self):
		frappe.db.set_value("Billing Profile", TEAM, "state", None)
		self.assertEqual(self._issue(), (180, "IGST"))

	def test_sez_has_no_split(self):
		_set_gst(TEAM, output_tax_type="GST", output_tax_rate=18, zero_rated=1, zero_rating_reason="SEZ")
		self.assertEqual(self._issue(), (0, None))

	def test_an_unknown_company_state_is_not_guessed(self):
		self.assertEqual(self._issue(company_state=None), (180, None))


class TestFilingUsesTheStoredSplit(SyncTestCase):
	def _filed_template(self, split):
		inv = self._invoice(team=TEAM)
		frappe.db.set_value("Invoice", inv, "gst_split", split)
		erpnext_sync.sync_invoice(inv)
		return self._sales_invoice()["taxes_and_charges"]

	def test_a_team_that_left_the_company_state_is_filed_as_issued(self):
		billing_team(TEAM, state="Karnataka")
		self.assertEqual(self._filed_template("CGST + SGST"), IN_STATE)

	def test_a_team_that_added_the_company_state_is_filed_as_issued(self):
		billing_team(TEAM, state="Maharashtra")
		self.assertEqual(self._filed_template("IGST"), OUT_STATE)


class TestRecordGstSplitPatch(IntegrationTestCase):
	def setUp(self):
		for team in (TEAM, OTHER_TEAM):
			ensure_team(team)
			complete_billing_profile(team)
		frappe.db.set_value("Billing Profile", OTHER_TEAM, "state", None)
		self.addCleanup(_forget_company_state)
		frappe.cache.set_value(gst.COMPANY_STATE_KEY, "27")

	def test_issued_gst_invoices_get_the_split_of_their_state(self):
		in_state = _insert_invoice(TEAM, "2026-05-31")
		stateless = _insert_invoice(OTHER_TEAM, "2026-05-31")
		untaxed = _insert_invoice(TEAM, "2026-04-30", output_tax_amount=0)
		unissued = _insert_invoice(TEAM, "2026-03-31", due_date=None)
		record_gst_split_on_issued_invoices.execute()
		self.assertEqual(
			[_split(n) for n in (in_state, stateless, untaxed, unissued)], ["CGST + SGST", "IGST", None, None]
		)

	def test_a_second_run_keeps_what_is_recorded(self):
		inv = _insert_invoice(TEAM, "2026-05-31")
		record_gst_split_on_issued_invoices.execute()
		frappe.db.set_value("Billing Profile", TEAM, "state", "Karnataka")
		record_gst_split_on_issued_invoices.execute()
		self.assertEqual(_split(inv), "CGST + SGST")

	def test_an_unknown_company_state_leaves_them_blank(self):
		_forget_company_state()
		inv = _insert_invoice(TEAM, "2026-05-31")
		record_gst_split_on_issued_invoices.execute()
		self.assertIsNone(_split(inv))


def _insert_invoice(team, period_end, **fields):
	period_start = frappe.utils.get_first_day(period_end)
	values = {
		"status": "Paid",
		"due_date": period_end,
		"output_tax_type": "GST",
		"output_tax_rate": 18,
		"output_tax_amount": 180,
		**fields,
	}
	doc = frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": team,
			"invoice_type": "Billable",
			"period_start": period_start,
			"period_end": period_end,
			"period_key": period_key_for(team, period_start, getdate(period_end)),
			"currency": "INR",
			**values,
		}
	)
	doc.db_insert()
	return doc.name


def _split(invoice):
	return frappe.db.get_value("Invoice", invoice, "gst_split") or None


def _forget_company_state():
	frappe.cache.delete_value([gst.COMPANY_STATE_KEY, gst.LAST_COMPANY_STATE_KEY])
