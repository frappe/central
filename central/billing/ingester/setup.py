# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Check and create what Central needs in the accounting system.

`check` only reads. `create_missing` creates what is missing and fills fields that
are blank on the company and the GST settings. Neither ever changes a value someone
has already set, or deletes anything.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import frappe

from central.billing.ingester import connection
from central.billing.ingester.settings import accounting_settings

EXISTS = "Exists"
MISSING = "Missing"
INCOMPLETE = "Incomplete"
CREATED = "Created"
UPDATED = "Updated"
FAILED = "Failed"

PRINT_FORMATS = Path(__file__).parent / "print_formats"

_CREATE_BY_HAND = "Central does not create this. Create it in the accounting system."


@dataclass
class Step:
	record: str
	doctype: str
	name: str | None
	check: Callable[[], str]
	apply: Callable[[], None] | None = None  # None: must exist, Central does not create it
	detail: str = ""


def check() -> list[dict]:
	"""What exists in the accounting system and what does not. Writes nothing."""
	return [_row(step, _safe(step.check, step)) for step in steps(accounting_settings())]


def create_missing() -> list[dict]:
	"""Create what is missing, fill what is blank, and keep a report of the run."""
	settings = accounting_settings()
	rows = [_run(step) for step in steps(settings)]
	settings.db_set(
		{"setup_ran_at": frappe.utils.now_datetime(), "setup_report": json.dumps(rows, indent=1)},
		update_modified=False,
	)
	return rows


def steps(s) -> list[Step]:
	"""Every record, in the order they depend on each other."""
	return [
		_must_exist("Company", "Company", s.company),
		_must_exist("Receivable account", "Account", s.receivable_account),
		_must_exist("Income account", "Account", s.income_account),
		_must_exist("Cost center", "Cost Center", s.cost_center),
		_must_exist("In-state tax template", "Sales Taxes and Charges Template", s.in_state_template),
		_must_exist("Out-of-state tax template", "Sales Taxes and Charges Template", s.out_state_template),
		_must_exist("SAC code", "GST HSN Code", s.sac_code),
		_account("Advance account", s.advance_account, s.advance_parent_account, "Receivable", None, s),
		*[
			_account(
				"Clearing account", row.clearing_account, s.clearing_parent_account, "Bank", row.currency, s
			)
			for row in s.gateways
		],
		_company_address(s),
		_company_fields(s),
		_overseas_supplies(),
		*[_mode_of_payment(mode, rows, s) for mode, rows in _by_mode(s.gateways).items()],
		_service_item(s),
		_series("Sales Invoice", [s.series_india_b2b, s.series_india_b2c, s.series_overseas]),
		_series("Payment Entry", [s.series_receipt_voucher]),
		_print_format(s.invoice_print_format, "Sales Invoice", "tax_invoice.html"),
		_print_format(s.receipt_voucher_print_format, "Payment Entry", "receipt_voucher.html"),
	]


# --- step builders ------------------------------------------------------------


def _must_exist(record: str, doctype: str, name: str | None) -> Step:
	return Step(record, doctype, name, lambda: _exists(doctype, name))


def _account(record, name, parent, account_type, currency, s) -> Step:
	def apply():
		if not parent:
			raise ValueError(f"set the parent account for {name} in Accounting Settings")
		connection.post(
			"api/resource/Account",
			{
				"account_name": _short_account_name(name),
				"parent_account": parent,
				"company": s.company,
				"account_type": account_type,
				"account_currency": currency or _company_currency(s.company),
			},
		)

	return Step(record, "Account", name, lambda: _exists("Account", name), apply)


def _company_address(s) -> Step:
	def state():
		if s.company_address_id and connection.fetch("Address", s.company_address_id):
			return EXISTS
		found = connection.find(
			"Address",
			[["Dynamic Link", "link_name", "=", s.company], ["is_your_company_address", "=", 1]],
		)
		if found:
			s.db_set("company_address_id", found[0].name, update_modified=False)
			return EXISTS
		return MISSING

	def apply():
		address = connection.post(
			"api/resource/Address",
			{
				"address_title": s.company,
				"address_type": "Billing",
				"address_line1": s.address_line1,
				"city": s.city,
				"state": s.state,
				"pincode": s.pincode,
				"country": "India",
				"gstin": s.company_gstin,
				"is_your_company_address": 1,
				"links": [{"link_doctype": "Company", "link_name": s.company}],
			},
		)
		s.db_set("company_address_id", address.name, update_modified=False)

	return Step("Company address", "Address", s.company_address_id, state, apply)


def _company_fields(s) -> Step:
	wanted = {
		"gstin": s.company_gstin,
		"gst_category": "Registered Regular",
		"book_advance_payments_in_separate_party_account": 1,
		"default_advance_received_account": s.advance_account,
	}
	return _fill_blanks("Company GST and advance settings", "Company", s.company, wanted)


def _overseas_supplies() -> Step:
	step = _fill_blanks(
		"Overseas and SEZ supplies", "GST Settings", "GST Settings", {"enable_overseas_transactions": 1}
	)
	step.detail = "Site-wide. Lets an invoice carry the Overseas or SEZ GST category."
	return step


def _fill_blanks(record: str, doctype: str, name: str | None, wanted: dict) -> Step:
	def blanks() -> dict:
		current = connection.fetch(doctype, name) or {}
		return {field: value for field, value in wanted.items() if value and not current.get(field)}

	def state():
		if not connection.fetch(doctype, name):
			return MISSING
		return INCOMPLETE if blanks() else EXISTS

	def apply():
		connection.put(_resource(doctype, name), blanks())

	return Step(record, doctype, name, state, apply)


def _mode_of_payment(mode: str, rows: list, s) -> Step:
	accounts = [{"company": s.company, "default_account": row.clearing_account} for row in rows[:1]]

	def state():
		current = connection.fetch("Mode of Payment", mode)
		if not current:
			return MISSING
		has_company = any(a.get("company") == s.company for a in current.get("accounts") or [])
		return EXISTS if has_company else INCOMPLETE

	def apply():
		current = connection.fetch("Mode of Payment", mode)
		if not current:
			connection.post(
				"api/resource/Mode of Payment",
				{"mode_of_payment": mode, "type": "Bank", "enabled": 1, "accounts": accounts},
			)
			return
		connection.put(
			_resource("Mode of Payment", mode), {"accounts": [*(current.get("accounts") or []), *accounts]}
		)

	return Step("Mode of payment", "Mode of Payment", mode, state, apply)


def _service_item(s) -> Step:
	def apply():
		connection.post(
			"api/resource/Item",
			{
				"item_code": s.service_item,
				"item_name": s.service_item,
				"item_group": s.item_group,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"gst_hsn_code": s.sac_code,
				"item_defaults": [{"company": s.company, "income_account": s.income_account}],
			},
		)

	return Step("Service item", "Item", s.service_item, lambda: _exists("Item", s.service_item), apply)


def _series(doctype: str, wanted: list[str]) -> Step:
	wanted = [series for series in wanted if series]

	def missing() -> list[str]:
		current = _series_options(doctype)
		return [series for series in wanted if series not in current]

	def apply():
		naming = connection.post("api/method/frappe.client.get", {"doctype": "Document Naming Settings"})
		options = [*_series_options(doctype), *missing()]
		connection.run_doc_method(
			{**naming, "transaction_type": doctype, "naming_series_options": "\n".join(options)},
			"update_series",
		)

	return Step(
		f"{doctype} naming series",
		"Document Naming Settings",
		", ".join(wanted),
		lambda: INCOMPLETE if missing() else EXISTS,
		apply,
	)


def _print_format(name: str, doc_type: str, template: str) -> Step:
	def apply():
		connection.post(
			"api/resource/Print Format",
			{
				"name": name,
				"doc_type": doc_type,
				"module": "Accounts",
				"standard": "No",
				"custom_format": 1,
				"print_format_type": "Jinja",
				"html": (PRINT_FORMATS / template).read_text(),
			},
		)

	return Step("Print format", "Print Format", name, lambda: _exists("Print Format", name), apply)


# --- helpers ------------------------------------------------------------------


def _run(step: Step) -> dict:
	state = _safe(step.check, step)
	if state in (MISSING, INCOMPLETE) and step.apply:
		try:
			step.apply()
			state = CREATED if state == MISSING else UPDATED
		except Exception as error:
			frappe.log_error(title=f"Accounting setup: {step.record}")
			step.detail = _error_text(error)
			state = FAILED
	return _row(step, state)


def _safe(check: Callable[[], str], step: Step) -> str:
	try:
		return check()
	except Exception as error:
		step.detail = _error_text(error)
		return FAILED


def _row(step: Step, state: str) -> dict:
	return {
		"record": step.record,
		"doctype": step.doctype,
		"name": step.name,
		"state": state,
		"detail": step.detail or (_CREATE_BY_HAND if state == MISSING and not step.apply else ""),
	}


def _exists(doctype: str, name: str | None) -> str:
	if not name:
		return MISSING
	return EXISTS if connection.fetch(doctype, name) else MISSING


def _series_options(doctype: str) -> list[str]:
	"""The naming series on offer for `doctype`: a site override first, else the DocType's own."""
	override = connection.find(
		"Property Setter",
		[["doc_type", "=", doctype], ["field_name", "=", "naming_series"], ["property", "=", "options"]],
		["value"],
	)
	if override:
		options = override[0].value
	else:
		fields = (connection.fetch("DocType", doctype) or {}).get("fields") or []
		options = next((f.get("options") for f in fields if f.get("fieldname") == "naming_series"), "")
	return [o.strip() for o in (options or "").split("\n") if o.strip()]


def _by_mode(rows) -> dict[str, list]:
	modes: dict[str, list] = {}
	for row in rows:
		modes.setdefault(row.mode_of_payment, []).append(row)
	return modes


def _short_account_name(name: str) -> str:
	"""`Customer Advances - ABBR` is created as `Customer Advances`."""
	return name.rsplit(" - ", 1)[0]


def _company_currency(company: str) -> str:
	return (connection.fetch("Company", company) or {}).get("default_currency") or "INR"


def _resource(doctype: str, name: str) -> str:
	from urllib.parse import quote

	return f"api/resource/{quote(doctype)}/{quote(name, safe='')}"


def _error_text(error: Exception) -> str:
	response = getattr(error, "response", None)
	if response is not None:
		try:
			body = response.json()
			return str(body.get("exception") or body.get("_server_messages") or body)[:500]
		except ValueError:
			return response.text[:500]
	return str(error)[:500]
