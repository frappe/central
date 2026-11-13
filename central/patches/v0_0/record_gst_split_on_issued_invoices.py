import frappe

from central.billing.india_gst import INDIA
from central.billing.ingester import gst
from central.billing.revenue.tax import split_for_state


def execute() -> None:
	"""Record on each issued GST invoice the split it was filed with, from the team's state today."""
	company_code = gst.known_company_state_code()
	if not company_code:
		frappe.logger("central").info("GST split not recorded: the company's GST state is not known yet.")
		return
	teams_by_split: dict[str, list[str]] = {}
	for team, state in _teams_with_unsplit_invoices():
		teams_by_split.setdefault(split_for_state(state, company_code), []).append(team)
	invoice = frappe.qb.DocType("Invoice")
	for split, teams in teams_by_split.items():
		_unsplit_invoices(frappe.qb.update(invoice)).where(invoice.team.isin(teams)).set(
			"gst_split", split
		).run()


def _teams_with_unsplit_invoices() -> list[tuple]:
	invoice = frappe.qb.DocType("Invoice")
	profile = frappe.qb.DocType("Billing Profile")
	query = (
		frappe.qb.from_(invoice)
		.join(profile)
		.on(profile.name == invoice.team)
		.select(invoice.team, profile.state)
		.distinct()
		.where(profile.country == INDIA)
	)
	return _unsplit_invoices(query).run()


def _unsplit_invoices(query):
	"""Issued INR invoices that charged GST and have no split recorded."""
	invoice = frappe.qb.DocType("Invoice")
	return (
		query.where(invoice.due_date.isnotnull())
		.where(invoice.currency == "INR")
		.where(invoice.output_tax_type == "GST")
		.where(invoice.output_tax_amount > 0)
		.where(invoice.gst_split.isnull() | (invoice.gst_split == ""))
	)
