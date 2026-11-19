import base64

import frappe
from frappe import _
from frappe.query_builder import Order

from central.billing.api.dashboard.outlook import get_next_payment

OPEN_INVOICE_STATES = ("Outstanding", "Overdue")


def _money(amount, currency: str) -> str:
	return frappe.utils.fmt_money(frappe.utils.flt(amount), currency=currency)


def get_next_bill(team: str, server: str, forecast: dict, currency: str) -> dict:
	"""This server's share of the team's next bill, from the team forecast, with what would
	stop the team's charge."""
	lines = [line for line in forecast["line_items"] if line.get("subscription_resource") == server]
	subtotal = frappe.utils.flt(sum(frappe.utils.flt(line["amount"]) for line in lines), 2)
	tax = get_tax_share(forecast.get("tax_amount"), forecast.get("subtotal"), subtotal)
	payment = get_next_payment(team)

	return {
		"amount": _money(subtotal + tax, currency),
		"subtotal": _money(subtotal, currency),
		"tax": _money(tax, currency) if tax else None,
		"tax_type": forecast.get("tax_type") if tax else None,
		"charge_on": payment["charge_on"],
		"days_left": forecast["days_remaining"],
		"lines": [
			{"item": line["item"], "detail": line.get("detail"), "amount": _money(line["amount"], currency)}
			for line in lines
		],
		"blockers": payment["blockers"],
	}


def get_tax_share(tax_amount: float | None, team_subtotal: float | None, server_subtotal: float) -> float:
	"""Tax is charged on the team's invoice, so a server's share follows that invoice's rate."""
	if not frappe.utils.flt(team_subtotal):
		return 0.0
	return frappe.utils.flt(
		server_subtotal * frappe.utils.flt(tax_amount) / frappe.utils.flt(team_subtotal), 2
	)


def get_server_invoices(team: str, server: str) -> list[dict]:
	"""This server's charges on each billable invoice of the team, newest first. An invoice that
	also names another server of the team is a statement only: no PDF and no payment here."""
	other_servers = set(frappe.get_all("Virtual Machine", {"team": team}, pluck="name")) - {server}
	statements = []

	for lines in _get_invoice_lines(team).values():
		invoice = lines[0]
		server_lines = [line for line in lines if line.subscription_resource == server]
		if not server_lines:
			continue

		subtotal = frappe.utils.flt(sum(frappe.utils.flt(line.amount) for line in server_lines), 2)
		tax = get_tax_share(invoice.output_tax_amount, invoice.subtotal, subtotal)
		is_whole_invoice = not any(line.subscription_resource in other_servers for line in lines)
		statements.append(
			{
				"name": invoice.name,
				"period_start": str(invoice.period_start),
				"period_end": str(invoice.period_end),
				"status": invoice.status,
				"amount": _money(subtotal + tax, invoice.currency),
				"has_pdf": is_whole_invoice and bool(invoice.erpnext_invoice),
				"can_pay": is_whole_invoice and invoice.status in OPEN_INVOICE_STATES,
			}
		)

	return statements


def _get_invoice_lines(team: str) -> dict[str, list]:
	"""The team's billable invoices, newest first, as rows of the invoice joined with each of its
	line items, keyed by invoice. One query."""
	invoice = frappe.qb.DocType("Invoice")
	line = frappe.qb.DocType("Invoice Line Item")
	rows = (
		frappe.qb.from_(invoice)
		.join(line)
		.on(line.parent == invoice.name)
		.select(
			invoice.name,
			invoice.period_start,
			invoice.period_end,
			invoice.status,
			invoice.currency,
			invoice.subtotal,
			invoice.output_tax_amount,
			invoice.erpnext_invoice,
			line.subscription_resource,
			line.amount,
		)
		.where(
			(invoice.team == team) & (invoice.invoice_type == "Billable") & (invoice.status != "Cancelled")
		)
		.orderby(invoice.period_start, order=Order.desc)
		.run(as_dict=True)
	)

	invoices: dict[str, list] = {}
	for row in rows:
		invoices.setdefault(row.name, []).append(row)
	return invoices


def assert_covers_only_server(team: str, server: str, invoice: str) -> None:
	"""Refuse an invoice that also names another server of the team, so a site shows nothing
	beyond its own server. The caller checks that the invoice is the team's."""
	other_servers = set(frappe.get_all("Virtual Machine", {"team": team}, pluck="name")) - {server}
	named = frappe.get_all("Invoice Line Item", {"parent": invoice}, pluck="subscription_resource")
	if other_servers.intersection(named):
		frappe.throw(
			_("This invoice also covers your team's other sites. Open it from the Frappe Cloud dashboard."),
			frappe.PermissionError,
		)


def get_server_invoice_pdf(team: str, server: str, invoice: str) -> dict:
	"""The statutory invoice PDF, as base64, because Pilot relays JSON only."""
	from central.billing.ingester.erpnext_sync import sales_invoice_pdf

	assert_covers_only_server(team, server, invoice)
	sales_invoice = frappe.db.get_value("Invoice", invoice, "erpnext_invoice")
	if not sales_invoice:
		frappe.throw(_("This invoice has not been issued yet, so it has no PDF."), frappe.DoesNotExistError)

	return {
		"filename": f"{sales_invoice.replace('/', '-')}.pdf",
		"content": base64.b64encode(sales_invoice_pdf(sales_invoice)).decode(),
	}
