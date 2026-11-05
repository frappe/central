import frappe
from frappe import _
from frappe.query_builder.functions import Count, DateFormat, Sum


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	"""Trial sites by product and the month they were ready: how many, how they ended, and their cost."""
	site = frappe.qb.DocType("Site")
	month = DateFormat(site.ready_at, "%Y-%m")
	rows = (
		frappe.qb.from_(site)
		.select(
			site.product,
			month.as_("month"),
			site.trial_state,
			site.trial_currency,
			Count("*").as_("sites"),
			Sum(site.trial_cost).as_("cost"),
		)
		.where(site.trial_state.isnotnull() & (site.trial_state != ""))
		.groupby(site.product, month, site.trial_state, site.trial_currency)
		.orderby(month, order=frappe.qb.desc)
	).run(as_dict=True)

	columns = [
		{
			"fieldname": "product",
			"label": _("Product"),
			"fieldtype": "Link",
			"options": "Product",
			"width": 140,
		},
		{"fieldname": "month", "label": _("Ready In"), "fieldtype": "Data", "width": 100},
		{"fieldname": "trial_state", "label": _("Trial State"), "fieldtype": "Data", "width": 120},
		{"fieldname": "sites", "label": _("Sites"), "fieldtype": "Int", "width": 80},
		{
			"fieldname": "cost",
			"label": _("Trial Cost"),
			"fieldtype": "Currency",
			"options": "trial_currency",
			"width": 120,
		},
		{
			"fieldname": "trial_currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		},
	]
	return columns, rows
