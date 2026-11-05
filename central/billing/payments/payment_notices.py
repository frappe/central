# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe

from central.billing.doctype.invoice.invoice import owed_filters
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated


def send_payment_reminders(now: datetime) -> list[dict]:
	"""Remind each team whose invoice is charged tomorrow and has no payment attempt yet.

	The hourly sweep calls this, so the reminder goes out within an hour of 24 hours
	before the payment date. `payment_reminder_sent_at` makes it once per invoice."""
	tomorrow = frappe.utils.add_days(now.date(), 1)
	waiting = frappe.get_all(
		"Invoice",
		filters=[
			*owed_filters(),
			["invoice_type", "=", "Billable"],
			["expected_collection", ">", 0],
			["payment_date", "=", tomorrow],
			["payment_reminder_sent_at", "is", "not set"],
		],
		pluck="name",
	)
	tried = _invoices_with_attempts(waiting)
	return each_isolated(
		"Payment reminder",
		"Invoice",
		[name for name in waiting if name not in tried],
		lambda name: send_payment_reminder(name, now),
	)


def send_payment_reminder(invoice: str, now: datetime) -> dict:
	"""Send one payment reminder. A rail that owes a pre-debit notice gets that notice instead."""
	from central.billing.payments import emandate

	doc = frappe.get_doc("Invoice", invoice)
	if emandate.is_notice_required(doc, None):
		return {"invoice": invoice, "skipped": "predebit_notice"}

	notifications.notify(
		doc.team,
		"Payment Reminder",
		context=get_payment_context(doc),
		reference_doctype="Invoice",
		reference_name=invoice,
	)
	frappe.db.set_value("Invoice", invoice, "payment_reminder_sent_at", now, update_modified=False)
	return {"invoice": invoice, "reminded": True}


def get_payment_context(invoice) -> dict:
	"""The amount, the payment date and the method a payment notice names."""
	return {
		"amount": frappe.utils.fmt_money(invoice.expected_collection, currency=invoice.currency),
		"payment_date": frappe.utils.formatdate(invoice.payment_date, "d MMMM yyyy"),
		"method": get_charging_method_label(invoice.team),
	}


def get_charging_method_label(team: str) -> str | None:
	"""The label of the method the next charge uses, or None when the team has none."""
	from central.billing.payments import collection

	methods = collection.ordered_methods(team)
	if not methods:
		return None
	return frappe.db.get_value("Payment Method", methods[0].name, "display_label") or methods[0].gateway


def _invoices_with_attempts(invoices: list[str]) -> set[str]:
	if not invoices:
		return set()
	return set(frappe.get_all("Payment Attempt", filters={"invoice": ["in", invoices]}, pluck="invoice"))
