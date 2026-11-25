# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Check that every name Central reads from the accounting system is there.

Central only reads this setup. The accounting system is where it is made and kept,
so this reports what is missing or wrong and never writes.
"""

from collections.abc import Callable
from dataclasses import dataclass

import frappe

from central.billing.ingester import connection
from central.billing.ingester.settings import accounting_settings

OK = "OK"
MISSING = "Missing"
WRONG = "Wrong"
NO_ACCESS = "No Access"
FAILED = "Failed"

# What ERPNext takes as a customer's receivable and advance account (its Customer form filters).
RECEIVABLE = {"account_type": "Receivable", "root_type": "Asset"}
ADVANCE = {"account_type": "Receivable", "root_type": "Liability"}


@dataclass
class Step:
	record: str
	doctype: str
	name: str | None
	check: Callable[[], tuple[str, str]]  # (state, detail)


def check() -> list[dict]:
	"""One row per record Central reads, with what is wrong with it, if anything."""
	return [_run(step) for step in steps(accounting_settings())]


def steps(s) -> list[Step]:
	return [
		_exists("Company", "Company", s.company),
		Step("Company address", "Address", s.company_address, lambda: _company_address(s)),
		*[step for row in s.receivable_accounts for step in _currency_accounts(row, s.company)],
		Step("Advances in a separate account", "Company", s.company, lambda: _separate_advances(s.company)),
		_exists("Cost center", "Cost Center", s.cost_center),
		_account("Promotional credit account", s.promotional_credit_account, s.company),
		*[step for row in s.gateways for step in _gateway(row, s.company)],
		Step("Service item", "Item", s.service_item, lambda: _service_item(s.service_item)),
		_exists("In-state tax template", "Sales Taxes and Charges Template", s.in_state_template),
		_exists("Out-of-state tax template", "Sales Taxes and Charges Template", s.out_state_template),
		Step("Overseas and SEZ supplies", "GST Settings", "GST Settings", _overseas_supplies),
		_series(
			"Sales Invoice", [s.series_india_b2b, s.series_india_b2c, s.series_overseas, s.series_credit_note]
		),
		_series("Payment Entry", [s.series_receipt_voucher]),
		_print_format(s.invoice_print_format, "Sales Invoice"),
		_print_format(s.receipt_voucher_print_format, "Payment Entry"),
	]


# --- checks -------------------------------------------------------------------


def _exists(record: str, doctype: str, name: str | None) -> Step:
	def check():
		return (OK, "") if _fetch(doctype, name) else (MISSING, "")

	return Step(record, doctype, name, check)


def _company_address(s) -> tuple[str, str]:
	if not s.company_address:
		found = connection.find(
			"Address",
			[["Dynamic Link", "link_name", "=", s.company], ["is_your_company_address", "=", 1]],
		)
		hint = f" The company has: {', '.join(a.name for a in found)}." if found else ""
		return MISSING, f"Set the company address.{hint}"
	address = _fetch("Address", s.company_address)
	if not address:
		return MISSING, ""
	if not address.get("gstin"):
		return WRONG, "It has no GSTIN, so no GST can be charged."
	return OK, f"GSTIN {address.gstin}"


def _currency_accounts(row, company: str) -> list[Step]:
	"""The accounts one currency is booked to. The kinds are the ones ERPNext accepts there."""
	currency = row.currency
	return [
		_account(f"{currency} receivable account", row.account, company, currency, **RECEIVABLE),
		_account(f"{currency} advance account", row.advance_account, company, currency, **ADVANCE),
		_account(f"{currency} income account", row.income_account, company, root_type="Income"),
		_account(f"{currency} wallet clearing account", row.wallet_clearing_account, company, currency),
	]


def _separate_advances(company: str) -> tuple[str, str]:
	if not (_fetch("Company", company) or {}).get("book_advance_payments_in_separate_party_account"):
		return WRONG, "The company does not book advances in a separate account."
	return OK, ""


def _account(record: str, name: str | None, company: str, currency: str | None = None, **expected) -> Step:
	"""An account that exists in `company`, is not a group, and has the currency and kind given."""

	def check():
		account = _fetch("Account", name)
		if not account:
			return MISSING, ""
		problem = _account_problem(account, company, currency, expected)
		return (WRONG, problem) if problem else (OK, "")

	return Step(record, "Account", name, check)


def _account_problem(account, company: str, currency: str | None, expected: dict) -> str | None:
	if account.get("company") != company:
		return f"It belongs to {account.get('company')}, not {company}."
	if account.get("is_group"):
		return "It is a group. Name an account under it."
	if currency and account.get("account_currency") != currency:
		return f"It is in {account.get('account_currency')}, not {currency}."
	for field, value in expected.items():
		if account.get(field) != value:
			return f"Its {field.replace('_', ' ')} is {account.get(field) or 'not set'}, not {value}."
	return None


def _gateway(row, company: str) -> list[Step]:
	def mode_of_payment():
		return (OK, "") if _fetch("Mode of Payment", row.mode_of_payment) else (MISSING, "")

	label = f"{row.gateway} {row.currency}"
	return [
		Step(f"{label}: mode of payment", "Mode of Payment", row.mode_of_payment, mode_of_payment),
		_account(f"{label}: clearing account", row.clearing_account, company, row.currency),
	]


def _service_item(name: str | None) -> tuple[str, str]:
	item = _fetch("Item", name)
	if not item:
		return MISSING, ""
	if not item.get("gst_hsn_code"):
		return WRONG, "It has no SAC code."
	return OK, f"SAC {item.gst_hsn_code}"


def _overseas_supplies() -> tuple[str, str]:
	settings = _fetch("GST Settings", "GST Settings") or {}
	if not settings.get("enable_overseas_transactions"):
		return WRONG, "Overseas transactions are off, so an export invoice cannot be saved."
	return OK, ""


def _series(doctype: str, wanted: list[str]) -> Step:
	wanted = [series for series in wanted if series]

	def check():
		missing = [series for series in wanted if series not in _series_options(doctype)]
		return (MISSING, "Not offered: " + ", ".join(missing)) if missing else (OK, "")

	return Step(f"{doctype} naming series", "Document Naming Settings", ", ".join(wanted), check)


def _print_format(name: str | None, doc_type: str) -> Step:
	def check():
		print_format = _fetch("Print Format", name)
		if not print_format:
			return MISSING, ""
		if print_format.get("doc_type") != doc_type:
			return WRONG, f"It is for {print_format.get('doc_type')}, not {doc_type}."
		return OK, ""

	return Step(f"{doc_type} print format", "Print Format", name, check)


# --- helpers ------------------------------------------------------------------


def _run(step: Step) -> dict:
	try:
		state, detail = step.check()
	except connection.NoAccess:
		state, detail = NO_ACCESS, "The accounting sync user cannot read this."
	except Exception as error:
		frappe.log_error(title=f"Accounting setup check: {step.record}")
		state, detail = FAILED, str(error)[:300]
	return {
		"record": step.record,
		"doctype": step.doctype,
		"name": step.name,
		"state": state,
		"detail": detail,
	}


def _fetch(doctype: str, name: str | None):
	return connection.fetch(doctype, name) if name else None


def _series_options(doctype: str) -> list[str]:
	"""The naming series on offer for `doctype`, site changes included."""
	meta = connection.call("frappe.desk.form.load.getdoctype", {"doctype": doctype}) or {}
	for doc in meta.get("docs") or []:
		if doc.get("name") != doctype:
			continue
		for field in doc.get("fields") or []:
			if field.get("fieldname") == "naming_series":
				return [o.strip() for o in (field.get("options") or "").split("\n") if o.strip()]
	return []
