# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe

from central.billing.doctype.invoice.invoice import owed_filters
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated


def notify_payment_scheduled(invoice) -> None:
	"""Tell the team what an opened invoice charges, after credit, and when.

	A rail that owes a pre-debit notice is charged at its pre-debit charge time, which can be
	a day after the payment date. Every other rail is charged on the payment date."""
	credit = frappe.utils.flt(invoice.credit_applied)
	context = {
		**get_payment_context(invoice),
		"payment_date": _format_date(invoice.predebit_charge_after or invoice.payment_date),
		"total": frappe.utils.fmt_money(invoice.total, currency=invoice.currency),
		"credit_applied": frappe.utils.fmt_money(credit, currency=invoice.currency) if credit > 0 else None,
	}
	notifications.notify(
		invoice.team,
		"Payment Scheduled",
		context=context,
		reference_doctype="Invoice",
		reference_name=invoice.name,
	)


def notify_payment_date_changed(profile) -> None:
	"""Tell the team its new payment day, and which invoice it applies to.

	A new profile has no earlier day, so it gets no notice. The change carries no
	reference, so a second change in the same hour is not deduplicated away."""
	if not profile.get_doc_before_save() or not profile.has_value_changed("payment_day"):
		return

	from central.billing.doctype.billing_profile.billing_profile import get_payment_date

	next_month = frappe.utils.add_months(frappe.utils.get_first_day(frappe.utils.nowdate()), 1)
	context = {
		"payment_day": get_ordinal(profile.payment_day),
		"next_payment_date": _format_date(get_payment_date(profile.team, next_month)),
		**_get_uncharged_invoice(profile.team),
	}
	notifications.notify(profile.team, "Payment Date Changed", context=context)


def _get_uncharged_invoice(team: str) -> dict:
	"""The issued invoice that is not charged yet. It keeps its payment date."""
	invoice = frappe.db.get_value(
		"Invoice",
		[
			*owed_filters(),
			["team", "=", team],
			["invoice_type", "=", "Billable"],
			["payment_date", ">=", frappe.utils.nowdate()],
		],
		["name", "payment_date"],
		as_dict=True,
		order_by="payment_date asc",
	)
	if not invoice:
		return {}
	return {"open_invoice": invoice.name, "open_payment_date": _format_date(invoice.payment_date)}


def get_ordinal(day: int) -> str:
	"""1st, 2nd, 3rd, 4th, ... 11th, 12th, 13th, ... 21st."""
	day = frappe.utils.cint(day)
	suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
	return f"{day}{suffix}"


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
		"payment_date": _format_date(invoice.payment_date),
		"method": get_charging_method_label(invoice.team),
	}


def get_charging_method_label(team: str) -> str | None:
	"""The label of the method the next charge uses, or None when the team has none."""
	from central.billing.payments import collection

	methods = collection.ordered_methods(team)
	if not methods:
		return None
	return frappe.db.get_value("Payment Method", methods[0].name, "display_label") or methods[0].gateway


def _format_date(value) -> str:
	return frappe.utils.formatdate(value, "d MMMM yyyy")


def _invoices_with_attempts(invoices: list[str]) -> set[str]:
	if not invoices:
		return set()
	return set(frappe.get_all("Payment Attempt", filters={"invoice": ["in", invoices]}, pluck="invoice"))
