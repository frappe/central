# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The accounting settings on Billing Settings, the setup check, and invoice PDFs."""

import re
from unittest.mock import patch

import frappe

from central.billing.api.dashboard import invoices as dashboard_invoices
from central.billing.ingester import connection, setup
from central.billing.ingester import settings as accounting
from central.billing.tests.accounting_fake import requires_accounting_system
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team, make_user

COMPANY = "Test Co"


def complete_setup() -> dict:
	"""An accounting system that has everything the settings below name."""
	return {
		("Company", COMPANY): {
			"book_advance_payments_in_separate_party_account": 1,
			"default_advance_received_account": "Customer Advances - TC",
		},
		("Address", "Test Co-Billing"): {"gstin": "27AAACZ9999Z1ZC"},
		("Account", "Debtors - TC"): {"account_currency": "INR"},
		("Account", "Customer Advances - TC"): {},
		("Account", "Sales - TC"): {},
		("Account", "Stripe Clearing - TC"): {"account_currency": "INR"},
		("Account", "Wallet Clearing - TC"): {"account_currency": "INR"},
		("Cost Center", "Main - TC"): {},
		("Account", "Promotional Credit - TC"): {},
		("Mode of Payment", "Stripe"): {},
		("Item", "Cloud Hosting"): {"gst_hsn_code": "998315"},
		("Sales Taxes and Charges Template", "In - TC"): {},
		("Sales Taxes and Charges Template", "Out - TC"): {},
		("GST Settings", "GST Settings"): {"enable_overseas_transactions": 1},
		("Print Format", "Cloud Tax Invoice"): {"doc_type": "Sales Invoice"},
		("Print Format", "Cloud Receipt Voucher"): {"doc_type": "Payment Entry"},
	}


SERIES = {
	"Sales Invoice": "ACC-SINV-.YYYY.-\nB2B/.TFY./.#####\nB2C/.TFY./.#####\nEXP/.TFY./.#####\nCN/.TFY./.#####",
	"Payment Entry": "ACC-PAY-.YYYY.-\nRV/.TFY./.######",
}


class FakeAccountingSystem:
	"""An in-memory, read-only stand-in for the remote site."""

	def __init__(self):
		self.records = complete_setup()
		self.series = dict(SERIES)
		self.forbidden = set()
		self.writes = []

	def fetch(self, doctype, name):
		if doctype in self.forbidden:
			raise connection.NoAccess(doctype)
		record = self.records.get((doctype, name))
		return frappe._dict(record, name=name) if record is not None else None

	def find(self, doctype, filters, fields=None):
		return [frappe._dict(name=n) for (dt, n) in self.records if dt == doctype]

	def call(self, method, params=None):
		options = self.series[params["doctype"]]
		fields = [{"fieldname": "naming_series", "options": options}]
		return {"docs": [{"name": params["doctype"], "fields": fields}]}

	def write(self, *args, **kwargs):
		self.writes.append(args)


@requires_accounting_system
class AccountingSetupTestCase(IntegrationTestCase):
	def setUp(self):
		self._conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		self._conf.start()
		self.remote = FakeAccountingSystem()
		self._patches = [
			*[
				patch(f"central.billing.ingester.connection.{fn}", getattr(self.remote, fn))
				for fn in ("fetch", "find", "call")
			],
			*[
				patch(f"central.billing.ingester.connection.{fn}", self.remote.write)
				for fn in ("post", "put")
			],
		]
		for p in self._patches:
			p.start()
		self._configure()

	def tearDown(self):
		for p in self._patches:
			p.stop()
		self._conf.stop()

	def _configure(self, **values):
		doc = frappe.get_doc("Billing Settings")
		doc.update(
			{
				"company": COMPANY,
				"company_address": "Test Co-Billing",
				"advance_account": "Customer Advances - TC",
				"income_account": "Sales - TC",
				"cost_center": "Main - TC",
				"promotional_credit_account": "Promotional Credit - TC",
				"in_state_template": "In - TC",
				"out_state_template": "Out - TC",
				**values,
			}
		)
		doc.set("receivable_accounts", [])
		doc.append(
			"receivable_accounts",
			{"currency": "INR", "account": "Debtors - TC", "wallet_clearing_account": "Wallet Clearing - TC"},
		)
		doc.set("gateways", [])
		doc.append(
			"gateways",
			{
				"gateway": frappe.get_all("Payment Gateway", pluck="name", limit=1)[0],
				"currency": "INR",
				"mode_of_payment": "Stripe",
				"clearing_account": "Stripe Clearing - TC",
			},
		)
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("Billing Settings", "Billing Settings")

	def _states(self):
		return {r["record"]: (r["state"], r["detail"]) for r in setup.check()}


class TestCheck(AccountingSetupTestCase):
	def test_a_complete_setup_is_all_ok(self):
		states = self._states()
		self.assertEqual({state for state, _ in states.values()}, {"OK"})
		self.assertEqual(self.remote.writes, [])  # the check never writes

	def test_missing_records_are_reported(self):
		del self.remote.records[("Item", "Cloud Hosting")]
		self.remote.series["Payment Entry"] = "ACC-PAY-.YYYY.-"
		states = self._states()
		self.assertEqual(states["Service item"][0], "Missing")
		self.assertEqual(states["Payment Entry naming series"], ("Missing", "Not offered: RV/.TFY./.######"))

	def test_wrong_setup_is_explained(self):
		self.remote.records[("Company", COMPANY)]["book_advance_payments_in_separate_party_account"] = 0
		self.remote.records[("Account", "Stripe Clearing - TC")]["account_currency"] = "USD"
		self.remote.records[("Print Format", "Cloud Tax Invoice")]["doc_type"] = "Delivery Note"
		states = self._states()
		gateway = frappe.get_doc("Billing Settings").gateways[0].gateway
		self.assertEqual(states["Advance account"][0], "Wrong")
		self.assertEqual(states[f"{gateway} INR: clearing account"][0], "Wrong")
		self.assertEqual(states["Sales Invoice print format"][0], "Wrong")

	def test_a_record_the_sync_user_cannot_read_is_flagged(self):
		self.remote.forbidden.add("Print Format")
		self.assertEqual(self._states()["Sales Invoice print format"][0], "No Access")

	def test_a_missing_company_address_names_the_candidates(self):
		self._configure(company_address="")
		state, detail = self._states()["Company address"]
		self.assertEqual(state, "Missing")
		self.assertIn("Test Co-Billing", detail)

	def test_names_are_saved_without_stray_spaces(self):
		self._configure(advance_account=" Customer Advances - TC ")
		self.assertEqual(
			frappe.db.get_single_value("Billing Settings", "advance_account"), "Customer Advances - TC"
		)

	def test_accounting_tab_shows_only_while_sync_is_on(self):
		doc = frappe.get_doc("Billing Settings")
		doc.run_method("onload")
		self.assertTrue(doc.get_onload().accounting_sync_enabled)
		frappe.local.conf["enable_erpnext_sync"] = 0
		doc.run_method("onload")
		self.assertFalse(doc.get_onload().accounting_sync_enabled)

	def test_refused_while_sync_is_off(self):
		frappe.local.conf["enable_erpnext_sync"] = 0
		with self.assertRaises(frappe.ValidationError):
			setup.check()


class TestInvoiceSeries(AccountingSetupTestCase):
	TEAM = "team-accounting-series"

	def _team(self, country, gstin=None, status=None):
		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM)
		frappe.db.set_value(
			"Billing Profile", self.TEAM, {"country": country, "gstin": gstin, "gst_status": status}
		)

	def test_series_by_customer(self):
		self._team("India", "27AABCT1111T1Z5", "Active")
		self.assertEqual(accounting.invoice_series(self.TEAM), "B2B/.TFY./.#####")
		self._team("India", "27AABCT1111T1Z5", "Cancelled")
		self.assertEqual(accounting.invoice_series(self.TEAM), "B2C/.TFY./.#####")
		self._team("India")
		self.assertEqual(accounting.invoice_series(self.TEAM), "B2C/.TFY./.#####")
		self._team("United States")
		self.assertEqual(accounting.invoice_series(self.TEAM), "EXP/.TFY./.#####")

	def test_default_series_fit_the_gst_limit(self):
		s = frappe.get_doc("Billing Settings")
		for series in (s.series_india_b2b, s.series_india_b2c, s.series_overseas, s.series_receipt_voucher):
			# `.TFY.` renders the fiscal year as 26-27.
			number = re.sub(r"\.#+", lambda m: "9" * (len(m.group()) - 1), series.replace(".TFY.", "26-27"))
			self.assertLessEqual(len(number), 16, number)
			self.assertRegex(number, r"^[A-Za-z0-9/-]+$")


class TestInvoicePdf(AccountingSetupTestCase):
	TEAM = "team-invoice-pdf"

	def setUp(self):
		super().setUp()
		ensure_team(self.TEAM)
		self.invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": self.TEAM,
				"invoice_type": "Billable",
				"status": "Paid",
				"period_start": "2026-08-01",
				"period_end": "2026-08-31",
				"currency": "INR",
				"subtotal": 500,
				"total": 590,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, frappe.session.user)

	def _download(self):
		frappe.local.response = frappe._dict()
		with (
			patch("central.billing.api.dashboard.invoices._require_view"),
			patch("central.billing.ingester.connection.download", return_value=b"%PDF-1.7") as download,
		):
			dashboard_invoices.download_invoice_pdf(self.invoice.name)
		return download

	def test_an_issued_invoice_downloads_with_the_configured_print_format(self):
		frappe.db.set_value("Invoice", self.invoice.name, "erpnext_invoice", "B2B/26-27/00001")
		download = self._download()
		self.assertEqual(download.call_args.args[0], "frappe.utils.print_format_generator.download_pdf")
		self.assertEqual(download.call_args.args[1]["print_format"], "Cloud Tax Invoice")
		self.assertEqual(download.call_args.args[1]["letterhead"], "No Letterhead")
		self.assertEqual(frappe.local.response.filecontent, b"%PDF-1.7")
		self.assertEqual(frappe.local.response.filename, "B2B-26-27-00001.pdf")

	def test_an_unissued_invoice_has_no_pdf(self):
		with self.assertRaises(frappe.DoesNotExistError):
			self._download()

	def test_another_team_cannot_download(self):
		frappe.db.set_value("Invoice", self.invoice.name, "erpnext_invoice", "B2B/26-27/00001")
		frappe.set_user(make_user("pdf-outsider@example.com"))
		with self.assertRaises(frappe.PermissionError):
			dashboard_invoices.download_invoice_pdf(self.invoice.name)


class TestTopUpReceipt(AccountingSetupTestCase):
	TEAM = "team-topup-receipt"

	def setUp(self):
		super().setUp()
		ensure_team(self.TEAM)
		self.entry = frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": self.TEAM,
				"entry_type": "Credit",
				"amount": 10000,
				"tax_amount": 1800,
				"currency": "INR",
				"gateway_payment_id": "Stripe:pi_receipt",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, frappe.session.user)

	def _download(self):
		frappe.local.response = frappe._dict()
		with (
			patch("central.billing.api.dashboard.invoices._require_view"),
			patch("central.billing.ingester.connection.download", return_value=b"%PDF-1.7") as download,
		):
			dashboard_invoices.download_topup_receipt(self.entry.name)
		return download

	def test_a_booked_top_up_downloads_its_receipt_voucher(self):
		self.entry.db_set("advance_id", "RV/26-27/000001")
		download = self._download()
		self.assertEqual(download.call_args.args[1]["doctype"], "Payment Entry")
		self.assertEqual(download.call_args.args[1]["print_format"], "Cloud Receipt Voucher")
		self.assertEqual(frappe.local.response.filename, "RV-26-27-000001.pdf")

	def test_a_top_up_not_yet_booked_has_no_receipt(self):
		with self.assertRaises(frappe.DoesNotExistError):
			self._download()

	def test_another_team_cannot_download(self):
		self.entry.db_set("advance_id", "RV/26-27/000001")
		frappe.set_user(make_user("receipt-outsider@example.com"))
		with self.assertRaises(frappe.PermissionError):
			dashboard_invoices.download_topup_receipt(self.entry.name)

	def test_the_wallet_history_says_which_top_ups_have_a_receipt(self):
		self.entry.db_set("advance_id", "RV/26-27/000001")
		with patch("central.billing.api.dashboard.invoices._resolve_team", return_value=self.TEAM):
			rows = dashboard_invoices.credit_ledger(self.TEAM)
		row = next(r for r in rows if r["name"] == self.entry.name)
		self.assertTrue(row["has_receipt"])
		self.assertEqual(row["tax_amount"], 1800)
		self.assertNotIn("advance_id", row)
