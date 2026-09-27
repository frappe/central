# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Accounting Settings and the setup that checks and creates its records."""

import re
from unittest.mock import patch

import frappe

from central.billing.ingester import settings as accounting
from central.billing.ingester import setup
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

COMPANY = "Test Co"
EXISTING = {
	("Company", COMPANY): {"default_currency": "INR", "gstin": None, "gst_category": "Unregistered"},
	("Account", "Debtors - TC"): {},
	("Account", "Sales - TC"): {},
	("Cost Center", "Main - TC"): {},
	("Sales Taxes and Charges Template", "In - TC"): {},
	("Sales Taxes and Charges Template", "Out - TC"): {},
	("GST HSN Code", "998315"): {},
	("GST Settings", "GST Settings"): {"enable_overseas_transactions": 0},
	("DocType", "Sales Invoice"): {"fields": [{"fieldname": "naming_series", "options": "ACC-SINV-.YYYY.-"}]},
	("DocType", "Payment Entry"): {"fields": [{"fieldname": "naming_series", "options": "ACC-PAY-.YYYY.-"}]},
}


class FakeAccountingSystem:
	"""An in-memory stand-in for the remote site."""

	def __init__(self, records: dict):
		self.records = {key: dict(value) for key, value in records.items()}
		self.writes = []
		self.series = {}

	def fetch(self, doctype, name):
		record = self.records.get((doctype, name))
		return frappe._dict(record, name=name) if record is not None else None

	def find(self, doctype, filters, fields=None):
		if doctype == "Property Setter":
			options = self.series.get(filters[0][2])
			return [frappe._dict(value=options)] if options else []
		return [
			frappe._dict(name=n) for (dt, n), r in self.records.items() if dt == doctype and r.get("mine")
		]

	def post(self, endpoint, payload):
		self.writes.append(("POST", endpoint, payload))
		if endpoint == "api/method/frappe.client.get":
			return frappe._dict(doctype="Document Naming Settings", name="Document Naming Settings")
		doctype = endpoint.rsplit("/", 1)[1].replace("%20", " ")
		name = self._name(doctype, payload)
		self.records[(doctype, name)] = dict(payload, mine=doctype == "Address")
		return frappe._dict(name=name)

	def put(self, endpoint, payload):
		self.writes.append(("PUT", endpoint, payload))
		_, doctype, name = endpoint.rsplit("/", 2)
		self.records[(doctype.replace("%20", " "), name.replace("%20", " "))].update(payload)

	def run_doc_method(self, doc, method, args=None):
		self.writes.append(("RUN", method, doc))
		self.series[doc["transaction_type"]] = doc["naming_series_options"]

	def _name(self, doctype, payload):
		if doctype == "Account":
			return f"{payload['account_name']} - TC"
		if doctype == "Address":
			return f"{payload['address_title']}-Billing"
		return payload.get("name") or payload.get("mode_of_payment") or payload.get("item_code")


class AccountingSetupTestCase(IntegrationTestCase):
	def setUp(self):
		self._conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		self._conf.start()
		self.remote = FakeAccountingSystem(EXISTING)
		self._remote = [
			patch(f"central.billing.ingester.connection.{fn}", getattr(self.remote, fn))
			for fn in ("fetch", "find", "post", "put", "run_doc_method")
		]
		for p in self._remote:
			p.start()
		self._configure()

	def tearDown(self):
		for p in self._remote:
			p.stop()
		self._conf.stop()

	def _configure(self):
		doc = frappe.get_doc("Accounting Settings")
		doc.update(
			{
				"company": COMPANY,
				"company_gstin": "27AAACZ9999Z1ZC",
				"company_address_id": None,
				"address_line1": "1 Test Road",
				"city": "Mumbai",
				"state": "Maharashtra",
				"pincode": "400001",
				"receivable_account": "Debtors - TC",
				"advance_account": "Customer Advances - TC",
				"advance_parent_account": "Current Liabilities - TC",
				"income_account": "Sales - TC",
				"cost_center": "Main - TC",
				"clearing_parent_account": "Bank Accounts - TC",
				"in_state_template": "In - TC",
				"out_state_template": "Out - TC",
			}
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
		frappe.clear_document_cache("Accounting Settings", "Accounting Settings")

	def _states(self, rows):
		return {(r["record"], r["name"]): r["state"] for r in rows}


class TestCheck(AccountingSetupTestCase):
	def test_check_writes_nothing(self):
		rows = setup.check()
		self.assertEqual(self.remote.writes, [])
		states = self._states(rows)
		self.assertEqual(states[("Receivable account", "Debtors - TC")], "Exists")
		self.assertEqual(states[("Advance account", "Customer Advances - TC")], "Missing")
		self.assertEqual(states[("Company GST and advance settings", COMPANY)], "Incomplete")

	def test_refused_while_sync_is_off(self):
		frappe.local.conf["enable_erpnext_sync"] = 0
		with self.assertRaises(frappe.ValidationError):
			setup.check()


class TestCreateMissing(AccountingSetupTestCase):
	def test_creates_what_is_missing_and_nothing_else(self):
		rows = setup.create_missing()
		states = self._states(rows)
		self.assertEqual(states[("Advance account", "Customer Advances - TC")], "Created")
		self.assertEqual(states[("Clearing account", "Stripe Clearing - TC")], "Created")
		self.assertEqual(states[("Mode of payment", "Stripe")], "Created")
		self.assertEqual(states[("Service item", "Cloud Hosting")], "Created")
		self.assertEqual(states[("Receivable account", "Debtors - TC")], "Exists")
		created = [w[1] for w in self.remote.writes if w[0] == "POST"]
		self.assertNotIn("api/resource/Company", created)
		self.assertTrue(frappe.db.get_single_value("Accounting Settings", "setup_ran_at"))

	def test_a_second_run_changes_nothing(self):
		setup.create_missing()
		self.remote.writes.clear()
		rows = setup.create_missing()
		self.assertEqual({r["state"] for r in rows}, {"Exists"})
		self.assertEqual(self.remote.writes, [])

	def test_only_blank_company_fields_are_filled(self):
		self.remote.records[("Company", COMPANY)]["gstin"] = "29AAACZ9999Z1Z1"
		setup.create_missing()
		company = self.remote.records[("Company", COMPANY)]
		self.assertEqual(company["gstin"], "29AAACZ9999Z1Z1")  # left as it was
		self.assertEqual(company["default_advance_received_account"], "Customer Advances - TC")
		self.assertEqual(company["gst_category"], "Unregistered")  # set already, so kept

	def test_new_series_follow_the_existing_ones(self):
		setup.create_missing()
		options = self.remote.series["Sales Invoice"].split("\n")
		self.assertEqual(options[0], "ACC-SINV-.YYYY.-")  # the default stays the default
		self.assertEqual(options[1:], ["B2B/.TFY./.#####", "B2C/.TFY./.#####", "EXP/.TFY./.#####"])

	def test_an_existing_mode_of_payment_gets_this_companys_account(self):
		self.remote.records[("Mode of Payment", "Stripe")] = {"accounts": [{"company": "Other Co"}]}
		setup.create_missing()
		accounts = self.remote.records[("Mode of Payment", "Stripe")]["accounts"]
		self.assertEqual([a["company"] for a in accounts], ["Other Co", COMPANY])

	def test_a_failed_step_is_reported_and_the_run_goes_on(self):
		real_post = self.remote.post

		def post(endpoint, payload):
			if endpoint == "api/resource/Item":
				raise RuntimeError("item rejected")
			return real_post(endpoint, payload)

		with patch("central.billing.ingester.connection.post", post):
			states = self._states(setup.create_missing())
		self.assertEqual(states[("Service item", "Cloud Hosting")], "Failed")
		self.assertEqual(states[("Print format", "Cloud Tax Invoice")], "Created")


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
		s = frappe.get_doc("Accounting Settings")
		for series in (s.series_india_b2b, s.series_india_b2c, s.series_overseas, s.series_receipt_voucher):
			# `.TFY.` renders the fiscal year as 26-27.
			number = re.sub(r"\.#+", lambda m: "9" * (len(m.group()) - 1), series.replace(".TFY.", "26-27"))
			self.assertLessEqual(len(number), 16, number)
			self.assertRegex(number, r"^[A-Za-z0-9/-]+$")
