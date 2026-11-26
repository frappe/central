# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An in-memory accounting system, and the settings that point at it, for tests."""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe

COMPANY = "Test Co"
COMPANY_ADDRESS = "Test Co-Billing"
COMPANY_GSTIN = "27AAACZ9999Z1ZC"
IN_STATE = "Output GST In-state - TC"
OUT_STATE = "Output GST Out-state - TC"

GST_ROWS = {
	IN_STATE: [
		{"account_head": "Output Tax SGST - TC", "rate": 9, "description": "SGST"},
		{"account_head": "Output Tax CGST - TC", "rate": 9, "description": "CGST"},
	],
	OUT_STATE: [{"account_head": "Output Tax IGST - TC", "rate": 18, "description": "IGST"}],
}


SYNC_MODE = "central.billing.ingester.connection.sync_mode"
ACCOUNTING_URL = "central.billing.ingester.connection._url"


def sync_mode(mode: str = "Automatic"):
	"""Patch the accounting sync mode of Billing Settings for a test."""
	return patch(SYNC_MODE, return_value=mode)


def requires_accounting_system(cls):
	"""Skip a test class on a site with no accounting system configured, such as CI.

	The tests fake every call, but they exercise an integration the site does not use.
	"""
	configured = frappe.db.get_single_value("Billing Settings", "accounting_url")
	return unittest.skipUnless(configured, "no accounting Site URL in Billing Settings")(cls)


class FakeAccountingSystem:
	"""Keeps what Central posts, and answers lookups the way the real API does."""

	def __init__(self):
		self.records = {
			("Address", COMPANY_ADDRESS): {"gstin": COMPANY_GSTIN},
			("Terms and Conditions", "Frappe Cloud"): {"terms": "Pay on time."},
			**{("Sales Taxes and Charges Template", t): {"taxes": rows} for t, rows in GST_ROWS.items()},
		}
		self.posted = []
		self.fail_on = set()  # doctypes whose next post is refused
		self.conversion_rate = 1.0

	def fetch(self, doctype, name):
		record = self.records.get((doctype, name))
		return frappe._dict(record, name=name) if record is not None else None

	def find(self, doctype, filters, fields=None):
		if any(len(condition) == 4 for condition in filters):
			return []  # a child table filter, such as a contact by email: nothing made by hand here
		return [
			frappe._dict(name=name)
			for (dt, name), record in self.records.items()
			if dt == doctype and all(self._matches(record, f) for f in filters)
		]

	def post(self, endpoint, payload):
		if endpoint.endswith("make_sales_return"):
			source = self.records[("Sales Invoice", payload["source_name"])]
			return frappe._dict(
				doctype="Sales Invoice",
				is_return=1,
				return_against=payload["source_name"],
				items=[dict(i, qty=-1) for i in source.get("items") or []],
				taxes=source.get("taxes") or [],
			)
		if endpoint.endswith("get_payment_entry"):
			amount = payload["party_amount"]
			return frappe._dict(
				doctype="Payment Entry",
				payment_type="Pay",
				party_type="Customer",
				paid_amount=amount,
				received_amount=amount,
				references=[
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": payload["dn"],
						"allocated_amount": -amount,
					}
				],
			)
		doctype = endpoint.rsplit("/", 1)[1].replace("%20", " ")
		if doctype in self.fail_on:
			self.fail_on.discard(doctype)
			raise RuntimeError(f"{doctype} refused")
		name = f"{doctype.split()[-1].upper()}-{len(self.posted) + 1}"
		record = dict(payload)
		if doctype == "Sales Invoice":
			record.update(self._invoice_totals(payload))
		if doctype == "Payment Entry":
			taxes = sum(frappe.utils.flt(t.get("tax_amount")) for t in payload.get("taxes") or [])
			record["total_taxes_and_charges"] = taxes
			record["unallocated_amount"] = 0 if payload.get("references") else payload["paid_amount"] - taxes
		self.records[(doctype, name)] = record
		self.posted.append((doctype, name, payload))
		return frappe._dict(name=name)

	def posts(self, doctype):
		return [payload for dt, _name, payload in self.posted if dt == doctype]

	def patches(self) -> ExitStack:
		stack = ExitStack()
		for fn in ("fetch", "find", "post"):
			stack.enter_context(patch(f"central.billing.ingester.connection.{fn}", getattr(self, fn)))
		return stack

	def _invoice_totals(self, payload) -> dict:
		# ERPNext rounds each total to the currency's precision. Tax-inclusive rows carve the
		# tax out of the line rates, so the grand total is exactly the lines.
		lines = frappe.utils.flt(
			sum(frappe.utils.flt(i["rate"]) * frappe.utils.flt(i["qty"]) for i in payload["items"]), 2
		)
		taxes = payload.get("taxes") or []
		rate = sum(frappe.utils.flt(t["rate"]) for t in taxes) / 100
		inclusive = any(t.get("included_in_print_rate") for t in taxes)
		net = frappe.utils.flt(lines / (1 + rate), 2) if inclusive else lines
		tax = (
			frappe.utils.flt(lines - net, 2)
			if inclusive
			else sum(frappe.utils.flt(net * frappe.utils.flt(t["rate"]) / 100, 2) for t in taxes)
		)
		allocated = sum(frappe.utils.flt(a["allocated_amount"]) for a in payload.get("advances") or [])
		return {
			"grand_total": frappe.utils.flt(net + tax, 2),
			"outstanding_amount": max(
				frappe.utils.flt(net + tax - allocated * (1 + (tax / net if net else 0)), 2), 0
			),
			"conversion_rate": self.conversion_rate,
		}

	@staticmethod
	def _matches(record, condition) -> bool:
		field, op, value = condition
		actual = record.get(field)
		if op == "like":
			return value.strip("%") in (actual or "")
		if field == "docstatus" and actual is None:
			actual = 1  # everything Central posts is submitted
		if field == "is_return" and actual is None:
			actual = 0
		return actual == value


def configure_accounting(**values) -> None:
	"""Point Billing Settings at the fake: company, accounts, gateways, templates."""
	doc = frappe.get_doc("Billing Settings")
	doc.update(
		{
			"company": COMPANY,
			"company_address": COMPANY_ADDRESS,
			"cost_center": "Main - TC",
			"invoice_terms": "Frappe Cloud",
			"promotional_credit_account": "Promotional Credit - TC",
			"in_state_template": IN_STATE,
			"out_state_template": OUT_STATE,
			**values,
		}
	)
	doc.set("receivable_accounts", [])
	for currency, account, region in (
		("INR", "Debtors - TC", "India"),
		("USD", "Debtors USD - TC", "Global"),
	):
		doc.append(
			"receivable_accounts",
			{
				"currency": currency,
				"account": account,
				"advance_account": f"Customer Advances {currency} - TC",
				"income_account": f"Sales {region} - TC",
				"wallet_clearing_account": f"Wallet Clearing {currency} - TC",
			},
		)
	doc.set("gateways", [])
	for currency in ("INR", "USD"):
		doc.append(
			"gateways",
			{
				"gateway": "Stripe",
				"currency": currency,
				"mode_of_payment": "Stripe",
				"clearing_account": f"Stripe Clearing {currency} - TC",
			},
		)
	doc.save(ignore_permissions=True)
	frappe.clear_document_cache("Billing Settings", "Billing Settings")


def billing_team(team: str, country="India", state="Maharashtra", gstin=None, currency="INR") -> str:
	"""A team whose customer records already exist in the fake."""
	from central.billing.payments.provisioning import ensure_tax_profile
	from central.billing.tests.utils import complete_billing_profile, ensure_team

	ensure_team(team)
	complete_billing_profile(team, currency=currency)
	frappe.db.set_value(
		"Billing Profile",
		team,
		{
			"country": country,
			"state": state,
			"gstin": gstin,
			"gst_status": "Active" if gstin else None,
			"profile_id": f"{team} Ltd",
			"address_id": f"{team} Ltd-Billing",
			"contact_id": f"{team} contact",
		},
	)
	if frappe.db.exists("Tax Profile", team):
		frappe.delete_doc("Tax Profile", team, force=True)
	ensure_tax_profile(team)
	return team
