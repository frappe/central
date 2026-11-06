# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _

from central.billing.doctype.invoice.invoice import is_owed, owed_filters
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated
from central.notification import engine


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


def notify_retry_failed(invoice: str) -> None:
	"""Tell the team a dunning retry failed, and why, when the latest attempt on the invoice failed."""
	last = frappe.get_all(
		"Payment Attempt", {"invoice": invoice}, order_by="creation desc", limit=1, pluck="name"
	)
	if not last:
		return
	attempt = frappe.get_doc("Payment Attempt", last[0])
	if attempt.status != "Failed":
		return

	count = frappe.db.count("Payment Attempt", {"invoice": invoice})
	reason = attempt.failure_reason or attempt.failure_code or "declined"
	notifications.notify(
		attempt.team,
		"Payment Retry",
		message=_("Payment retry {0} for invoice {1} failed: {2}").format(count, invoice, reason),
		reference_doctype="Invoice",
		reference_name=invoice,
	)


def notify_invoice_overdue(invoice: str, team: str) -> None:
	"""Tell the team an invoice is overdue, and the action that settles it in its collection mode."""
	notifications.notify(
		team,
		"Invoice Overdue",
		message=_get_overdue_message(invoice, team),
		context={"invoice": invoice},
		reference_doctype="Invoice",
		reference_name=invoice,
	)


def _get_overdue_message(invoice: str, team: str) -> str:
	"""A charge still in flight can settle the invoice, so the team is told how to avoid suspension
	if it does not. Otherwise a Manual Checkout team pays by hand and a Prepaid team tops up its
	wallet (ADR 0005)."""
	from central.billing.payments import charges

	if charges.in_flight_attempt(invoice):
		suspends_on = frappe.db.get_value("Invoice", invoice, "suspends_on")
		return _(
			"Invoice {0} is overdue and your payment is still processing. Add credit to your wallet "
			"now to avoid suspension on {1}. If the payment also goes through, we will refund it."
		).format(invoice, _format_date(suspends_on))

	mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	if mode == "Manual Checkout":
		return _("Invoice {0} is overdue. Pay it now to avoid suspension.").format(invoice)
	if mode == "Prepaid":
		return _("Invoice {0} is overdue. Top up your wallet to settle it and avoid suspension.").format(
			invoice
		)
	return _("Invoice {0} is overdue. Please settle it to avoid suspension.").format(invoice)


def notify_payment_refunded(refund) -> None:
	"""Tell the team a payment that landed on an invoice already paid went back to where it came from."""
	method = frappe.db.get_value("Payment Attempt", refund.payment_attempt, "payment_method")
	notifications.notify(
		refund.team,
		"Payment Refunded",
		context={
			"paid_invoice": refund.invoice,
			"amount": frappe.utils.fmt_money(refund.amount, currency=refund.currency),
			"method": frappe.db.get_value("Payment Method", method, "display_label") if method else None,
		},
		reference_doctype="Refund",
		reference_name=refund.name,
	)


def notify_team_suspended(invoice, suspends_on) -> None:
	"""Tell the team dunning suspended it for `invoice`, and leave the reason on the invoice."""
	invoice.add_comment(
		"Info", f"Suspended for non-payment on {suspends_on}; running servers stopped, data preserved."
	)
	engine.dispatch(
		invoice.team,
		"server_suspended",
		message=_(
			"Your account was suspended because invoice {0} is unpaid. Running servers were stopped "
			"and data is preserved. Pay the invoice to restore them."
		).format(invoice.name),
		reference_doctype="Invoice",
		reference_name=invoice.name,
	)


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
	"""Send one payment reminder. A method that owes a pre-debit notice gets that notice instead."""
	from central.billing.payments import emandate

	doc = frappe.get_doc("Invoice", invoice)
	if not _is_reminder_due(doc, now):
		return {"invoice": invoice, "skipped": "not_due"}
	gateway = _get_charged_gateway(doc.team)
	if gateway and emandate.is_notice_required(doc, gateway):
		return {"invoice": invoice, "skipped": "predebit_notice"}
	if not _has_claimed_reminder(invoice, now):
		return {"invoice": invoice, "skipped": "already_reminded"}

	notifications.notify(
		doc.team,
		"Payment Reminder",
		context=get_payment_context(doc),
		reference_doctype="Invoice",
		reference_name=invoice,
	)
	return {"invoice": invoice, "reminded": True}


def _get_charged_gateway(team: str) -> str | None:
	"""The gateway of the method the charge uses first, or None when the team has no method."""
	from central.billing.payments import collection

	methods = collection.ordered_methods(team)
	return methods[0].gateway if methods else None


def _has_claimed_reminder(invoice: str, now: datetime) -> bool:
	"""Stamp the reminder on the invoice unless another sweep did it first. Only the sweep whose
	update changes the row sends, so two overlapping sweeps send one reminder."""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.update(invoice_tbl).set(invoice_tbl.payment_reminder_sent_at, now).where(
		invoice_tbl.name == invoice
	).where(invoice_tbl.payment_reminder_sent_at.isnull()).run()
	return frappe.db._cursor.rowcount == 1


def _is_reminder_due(invoice, now: datetime) -> bool:
	"""The invoice can settle or be charged after the sweep selected it, so it is checked again.

	1. It is still owed, with an amount to charge.
	2. It is charged tomorrow.
	3. It has no reminder yet and no payment attempt."""
	return (
		is_owed(invoice)
		and frappe.utils.flt(invoice.expected_collection) > 0
		and frappe.utils.getdate(invoice.payment_date) == frappe.utils.add_days(now.date(), 1)
		and not invoice.payment_reminder_sent_at
		and not _invoices_with_attempts([invoice.name])
	)


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
