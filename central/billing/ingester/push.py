# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Send one record to the accounting system for an operator, or show what would be sent.

In Manual mode nothing reaches the accounting system any other way. An operator checks a
record with `preview`, then sends it with `push`. A push also sends what the record needs
first: the team's customer, then its advances. Each step commits on its own, so a later
failure keeps what was made and a retry does not make it twice. The push stops at the
first step that fails and says why.
"""

from collections.abc import Callable, Iterator

import frappe
from frappe import _

from central.billing.ingester import advance, connection, customer, erpnext_sync
from central.billing.ingester.locks import hold_until_transaction_ends
from central.billing.platform.jobs import each_isolated

# Placeholder for a customer the push would create first.
NEW_CUSTOMER = "(new customer)"
# Customer, address, contact and the update pass.
CUSTOMER_STEPS = 4
# Refund steps one push takes at most: each refund needs a credit note, a payment and a reversal.
REFUND_STEPS = 20

Step = tuple[str, Callable[[], object]]


def push(doctype: str, name: str) -> dict:
	"""Send the record and what it needs first. Returns the steps sent, and the one that failed."""
	_require_enabled()
	return _send(doctype, name, _steps_for(doctype, name))


def preview(doctype: str, name: str) -> dict:
	"""What a push would send now. Reads from the accounting system, writes nothing."""
	_require_enabled()
	if doctype == "Billing Profile":
		return _preview_customer(frappe.get_doc("Billing Profile", name))
	if doctype == "Credit Ledger Entry":
		return _preview_advance(frappe.get_doc("Credit Ledger Entry", name))
	if doctype == "Invoice":
		return _preview_invoice(frappe.get_doc("Invoice", name))
	frappe.throw(_("A {0} is not sent to the accounting system.").format(doctype))


def is_offered() -> bool:
	"""Whether a form shows the send buttons: the sync is not Off and the user is an operator."""
	from central.billing import authz

	return connection.enabled() and authz.is_operator()


def _steps_for(doctype: str, name: str) -> Iterator[Step]:
	if doctype == "Billing Profile":
		_require_sync_allowed(name)
		return _customer_steps(name)
	if doctype == "Credit Ledger Entry":
		return _advance_steps(frappe.get_doc("Credit Ledger Entry", name))
	if doctype == "Invoice":
		return _invoice_steps(frappe.get_doc("Invoice", name))
	frappe.throw(_("A {0} is not sent to the accounting system.").format(doctype))


def _send(doctype: str, name: str, steps: Iterator[Step]) -> dict:
	"""Run each step in its own transaction, and stop at the first that fails."""
	outcome = {"sent": [], "failed": None, "error": None}

	def take(step: Step):
		label, send = step
		try:
			result = send()
		except Exception as error:
			outcome.update(failed=label, error=str(error))
			raise  # each_isolated undoes the step and keeps an Error Log of it
		if isinstance(result, dict) and result.get("error"):
			outcome.update(failed=label, error=result["error"])  # recorded, so not undone
		else:
			outcome["sent"].append(label)
		return result

	def until_failure():
		for step in steps:
			if outcome["failed"]:
				return
			yield step

	each_isolated("Accounting push", doctype, until_failure(), take, reference=name)
	return outcome


def _customer_steps(team: str) -> Iterator[Step]:
	"""The customer, address and contact while one is missing, then one update pass."""
	following = []

	def step():
		if not hold_until_transaction_ends(f"customer-sync::{team}"):
			frappe.throw(_("The customer of team {0} is being sent. Try again in a minute.").format(team))
		following.append(customer.take_next_step(frappe.get_doc("Billing Profile", team)))

	for number in range(1, CUSTOMER_STEPS + 1):
		yield _("Customer step {0}").format(number), step
		if not following or not following[-1]:
			return  # failed, or the update pass ran


def _advance_steps(credit) -> Iterator[Step]:
	if not credit.gateway_payment_id:
		frappe.throw(_("{0} is not a paid top-up, so it has no advance.").format(credit.name))
	yield from _missing_customer_steps(credit.team)
	yield _("Advance for {0}").format(credit.name), lambda: advance.sync_advance(credit.name)


def _invoice_steps(inv) -> Iterator[Step]:
	from central.billing.payments.corrections import next_accounting_step

	if inv.invoice_type != "Billable" or inv.status not in ("Paid", "Cancelled"):
		frappe.throw(_("Only a paid billable invoice, or one cancelled after it was paid, is sent."))
	yield from _missing_customer_steps(inv.team)
	for entry in _top_ups_without_advance(inv.team):
		yield _("Advance for {0}").format(entry), lambda entry=entry: advance.sync_advance(entry)
	if inv.status == "Paid":
		yield _("Sales Invoice for {0}").format(inv.name), lambda: _sync_invoice(inv.name)
	for number in range(1, REFUND_STEPS + 1):
		step = next_accounting_step(inv.name)
		if not step:
			return
		yield _("Refund step {0}").format(number), step


def _missing_customer_steps(team: str) -> Iterator[Step]:
	if not frappe.db.get_value("Billing Profile", team, "contact_id"):
		_require_sync_allowed(team)
		yield from _customer_steps(team)


def _require_sync_allowed(team: str) -> None:
	if not customer.is_sync_allowed(frappe.get_doc("Billing Profile", team)):
		frappe.throw(
			_(
				"Team {0} is not sent to the accounting system. Its billing details are incomplete, it is internal or a staging trial, or it has nothing billable yet."
			).format(team)
		)


def _sync_invoice(invoice: str) -> dict:
	"""The Sales Invoice and card payment. A failed try is recorded on the invoice and its error returned."""
	result = erpnext_sync.sync_invoice(invoice)
	if "failed" in result or "retry_scheduled" in result:
		result["error"] = frappe.db.get_value("Invoice", invoice, "erpnext_sync_error")
	return result


def _top_ups_without_advance(team: str) -> list[str]:
	return frappe.get_all(
		"Credit Ledger Entry",
		filters=[["team", "=", team], ["gateway_payment_id", "is", "set"], ["advance_id", "is", "not set"]],
		pluck="name",
		order_by="creation asc",
	)


def _preview_customer(profile) -> dict:
	return {
		"Customer": customer.customer_payload(profile),
		"Address": customer.address_payload(profile),
		"Contact": customer.contact_payload(profile),
	}


def _preview_advance(credit) -> dict:
	if not credit.gateway_payment_id:
		frappe.throw(_("{0} is not a paid top-up, so it has no advance.").format(credit.name))
	gateway, payment_id = advance.split_payment_id(credit.gateway_payment_id)
	payload = advance.payment_entry_payload(credit, _customer_or_new(credit.team), gateway, payment_id)
	return {"Payment Entry": payload}


def _preview_invoice(inv) -> dict:
	erpnext_sync.fill_state_for_filing(inv)  # in memory only, as the push would file it
	return {"Sales Invoice": erpnext_sync.build_sales_invoice(inv, _customer_or_new(inv.team))}


def _customer_or_new(team: str) -> str:
	return frappe.db.get_value("Billing Profile", team, "profile_id") or NEW_CUSTOMER


def _require_enabled() -> None:
	if not connection.enabled():
		frappe.throw(_("The accounting sync is Off. Set Sync Mode in Billing Settings first."))
