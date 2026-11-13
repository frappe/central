# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An issued invoice keeps the state its GST was charged and filed with."""

from unittest.mock import patch

import frappe
import requests
from frappe.utils import getdate

from central.billing.doctype.invoice.invoice import period_key_for
from central.billing.ingester import erpnext_sync
from central.billing.ingester.gst_state_backfill import record_missing_gst_states
from central.billing.payments import corrections
from central.billing.revenue import invoicing
from central.billing.revenue.tax import gst_split_for_invoice
from central.billing.tests.accounting_fake import IN_STATE, OUT_STATE, billing_team
from central.billing.tests.test_corrections import CorrectionsTestCase
from central.billing.tests.test_erpnext_sync import SyncTestCase
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-gst-state"
PLAN = "bundle-gst-state"
COMPANY_STATE = "central.billing.ingester.gst.cached_company_state_code"
FETCH = "central.billing.ingester.connection.fetch"


def _set_gst(team, **kw):
	frappe.db.delete("Tax Profile", {"team": team})
	frappe.get_doc({"doctype": "Tax Profile", "team": team, **kw}).insert(ignore_permissions=True)


def _forget_versions():
	frappe.db.delete("Version", {"ref_doctype": "Billing Profile", "docname": TEAM})


class TestStateAtIssue(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		sub = make_billing_subscription(TEAM, "ap-south-1", PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		complete_billing_profile(TEAM)
		self.addCleanup(_forget_versions)
		_set_gst(TEAM, output_tax_type="GST", output_tax_rate=18)
		self.invoice = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")

	def _issue(self):
		invoicing.open_and_collect(self.invoice, collect=False)
		return frappe.db.get_value(
			"Invoice", self.invoice, ["output_tax_amount", "gst_state", "gst_state_recorded"]
		)

	def test_the_team_state_is_recorded(self):
		self.assertEqual(self._issue(), (180, "Maharashtra", 1))

	def test_no_state_is_recorded_as_none(self):
		frappe.db.set_value("Billing Profile", TEAM, "state", None)
		self.assertEqual(self._issue(), (180, None, 1))

	def test_sez_is_not_recorded(self):
		_set_gst(TEAM, output_tax_type="GST", output_tax_rate=18, zero_rated=1, zero_rating_reason="SEZ")
		self.assertEqual(self._issue(), (0, None, 0))

	def test_an_untaxed_internal_team_is_not_recorded(self):
		frappe.db.set_value("Billing Profile", TEAM, "is_internal", 1)
		self.addCleanup(frappe.db.set_value, "Billing Profile", TEAM, "is_internal", 0)
		self.assertEqual(self._issue(), (0, None, 0))


class TestFilingFollowsTheRecordedState(SyncTestCase):
	"""The company is in Maharashtra (27)."""

	def _filed(self, team_state, recorded_state, recorded=1):
		billing_team(TEAM, state=team_state)
		inv = self._invoice(team=TEAM)
		frappe.db.set_value("Invoice", inv, {"gst_state": recorded_state, "gst_state_recorded": recorded})
		erpnext_sync.sync_invoice(inv)
		filed = self._sales_invoice()
		return filed["place_of_supply"], filed["taxes_and_charges"]

	def test_a_team_that_left_the_company_state(self):
		self.assertEqual(self._filed("Karnataka", "Maharashtra"), ("27-Maharashtra", IN_STATE))

	def test_a_team_that_moved_into_the_company_state(self):
		self.assertEqual(self._filed("Maharashtra", "Karnataka"), ("29-Karnataka", OUT_STATE))

	def test_a_team_that_had_no_state(self):
		self.assertEqual(self._filed("Maharashtra", None), (None, OUT_STATE))

	def test_not_recorded_follows_the_team_state(self):
		self.assertEqual(self._filed("Karnataka", None, recorded=0), ("29-Karnataka", OUT_STATE))


class TestRefundFollowsTheRecordedState(CorrectionsTestCase):
	def test_returned_gst_is_filed_as_the_invoice_was(self):
		inv = self._paid_invoice()
		frappe.db.set_value("Invoice", inv, {"gst_state": "Karnataka", "gst_state_recorded": 1})
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)

		wallet = self._refund(inv, "Wallet")
		advance = next(
			p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == f"{wallet.name}-advance"
		)
		self.assertEqual(advance["place_of_supply"], "29-Karnataka")
		self.assertEqual([t["account_head"] for t in advance["taxes"]], ["Output Tax IGST - TC"])


class TestSplitLabel(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		self.addCleanup(_forget_versions)

	def _split(self, company_state="27", **fields):
		invoice = frappe._dict(
			{
				"team": TEAM,
				"output_tax_type": "GST",
				"output_tax_amount": 180,
				"gst_state_recorded": 1,
				**fields,
			}
		)
		with patch(COMPANY_STATE, return_value=company_state):
			return gst_split_for_invoice(invoice)

	def test_recorded_company_state_is_cgst_and_sgst(self):
		frappe.db.set_value("Billing Profile", TEAM, "state", "Karnataka")
		self.assertEqual(self._split(gst_state="Maharashtra"), "CGST + SGST")

	def test_recorded_no_state_is_igst(self):
		self.assertEqual(self._split(gst_state=None), "IGST")

	def test_not_recorded_follows_the_team_state(self):
		self.assertEqual(self._split(gst_state=None, gst_state_recorded=0), "CGST + SGST")

	def test_no_gst_has_no_split(self):
		self.assertIsNone(self._split(gst_state="Karnataka", output_tax_amount=0))

	def test_an_unknown_company_state_is_not_guessed(self):
		self.assertIsNone(self._split(company_state=None, gst_state="Karnataka"))


class TestBackfillFromTheFiling(SyncTestCase):
	"""A synced invoice takes the place of supply on its Sales Invoice."""

	def setUp(self):
		super().setUp()
		billing_team(TEAM, state="Maharashtra")
		self.addCleanup(_forget_versions)

	def _synced(self, sales_invoice, place_of_supply):
		self.remote.records[("Sales Invoice", sales_invoice)] = {"place_of_supply": place_of_supply}
		return _insert_invoice(TEAM, "2026-05-31", erpnext_invoice=sales_invoice)

	def test_the_filed_state_is_recorded(self):
		inv = self._synced("SINV-1", "29-Karnataka")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), ("Karnataka", 1))

	def test_a_filing_without_a_place_of_supply_is_recorded_as_none(self):
		inv = self._synced("SINV-1", None)
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), (None, 1))

	def test_an_unreachable_accounting_system_is_tried_again(self):
		first = self._synced("SINV-1", "29-Karnataka")
		second = _insert_invoice(TEAM, "2026-04-30", erpnext_invoice="SINV-2")
		with patch(FETCH, side_effect=requests.ConnectionError) as fetch:
			record_missing_gst_states()
		self.assertEqual(fetch.call_count, 1)
		self.assertEqual([_recorded(first), _recorded(second)], [(None, 0), (None, 0)])

		record_missing_gst_states()
		self.assertEqual(_recorded(first), ("Karnataka", 1))


class TestBackfillFromHistory(IntegrationTestCase):
	"""An unsynced invoice takes the team's state when it was issued."""

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		_forget_versions()
		self.addCleanup(_forget_versions)

	def test_the_last_state_set_by_issue(self):
		_state_change("Karnataka", "Goa", "2026-05-01")
		_state_change("Goa", "Maharashtra", "2026-07-01")
		inv = _insert_invoice(TEAM, "2026-05-31", creation="2026-06-01 10:00:00")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), ("Goa", 1))

	def test_the_state_before_a_later_change(self):
		_state_change(None, "Maharashtra", "2026-07-01")
		inv = _insert_invoice(TEAM, "2026-05-31", creation="2026-06-01 10:00:00")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), (None, 1))

	def test_the_issue_time_comes_from_the_audit_trail(self):
		_state_change("Karnataka", "Goa", "2026-06-15")
		inv = _insert_invoice(TEAM, "2026-05-31", creation="2026-06-01 10:00:00")
		_issued_event(inv, "2026-06-20 10:00:00")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), ("Goa", 1))

	def test_an_unchanged_state_is_the_current_one(self):
		inv = _insert_invoice(TEAM, "2026-05-31")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), ("Maharashtra", 1))

	def test_a_second_run_keeps_what_is_recorded(self):
		inv = _insert_invoice(TEAM, "2026-05-31")
		record_missing_gst_states()
		frappe.db.set_value("Billing Profile", TEAM, "state", "Karnataka")
		record_missing_gst_states()
		self.assertEqual(_recorded(inv), ("Maharashtra", 1))

	def test_only_issued_gst_invoices_are_recorded(self):
		untaxed = _insert_invoice(TEAM, "2026-04-30", output_tax_amount=0)
		unissued = _insert_invoice(TEAM, "2026-03-31", due_date=None)
		usd = _insert_invoice(TEAM, "2026-02-28", currency="USD")
		record_missing_gst_states()
		self.assertEqual({_recorded(n) for n in (untaxed, unissued, usd)}, {(None, 0)})


def _insert_invoice(team, period_end, **fields):
	period_start = frappe.utils.get_first_day(period_end)
	values = {
		"status": "Paid",
		"due_date": period_end,
		"currency": "INR",
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
			**values,
		}
	)
	doc.db_insert()
	return doc.name


def _state_change(old, new, at):
	version = frappe.get_doc(
		{
			"doctype": "Version",
			"ref_doctype": "Billing Profile",
			"docname": TEAM,
			"data": frappe.as_json({"changed": [["state", old, new]]}),
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Version", version.name, "creation", at, update_modified=False)


def _issued_event(invoice, at):
	frappe.get_doc(
		{
			"doctype": "Billing Event",
			"team": TEAM,
			"occurred_at": at,
			"event_type": "Invoice Issued",
			"subject_doctype": "Invoice",
			"subject": invoice,
			"actor": "scheduler",
		}
	).insert(ignore_permissions=True, ignore_links=True)


def _recorded(invoice):
	state, recorded = frappe.db.get_value("Invoice", invoice, ["gst_state", "gst_state_recorded"])
	return state or None, recorded
