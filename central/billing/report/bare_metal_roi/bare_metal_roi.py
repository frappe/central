# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import date_diff, flt, getdate

from central.billing.report._capacity import active_machines
from central.billing.report._columns import column, inr
from central.billing.report._economics import to_inr


def execute(filters: dict | None = None):
	"""Whether the hardware pays for itself: cost to date against what its servers earned, per machine.

	Earned counts invoices of the servers on the machine today, since it went into service. A
	server that moved hosts counts on its current host."""
	filters = filters or {}
	machines = active_machines(filters.get("region"))
	incidents = _incidents([m.name for m in machines])
	earned = _earned_by_host()
	rows = [
		_row(machine, incidents.get(machine.name, []), earned.get(machine.atlas_host_id, 0.0))
		for machine in machines
	]
	return get_columns(), rows, _message(rows), _chart(rows), _summary(rows)


def _incidents(machines: list[str]) -> dict[str, list]:
	grouped = defaultdict(list)
	for row in frappe.get_all(
		"Metal Server Incident",
		filters={"parenttype": "Metal Server", "parent": ["in", machines]},
		fields=["parent", "repair_cost_inr", "downtime_hours"],
	):
		grouped[row.parent].append(row)
	return grouped


def _earned_by_host() -> dict[str, float]:
	"""Pre-tax revenue billed, in INR, per Atlas host, through the servers placed on it."""
	line = frappe.qb.DocType("Invoice Line Item")
	invoice = frappe.qb.DocType("Invoice")
	server = frappe.qb.DocType("Virtual Machine")
	rows = (
		frappe.qb.from_(line)
		.join(invoice)
		.on(invoice.name == line.parent)
		.join(server)
		.on(server.name == line.subscription_resource)
		.select(server.atlas_host_id, invoice.currency, Sum(line.amount).as_("amount"))
		.where(line.parenttype == "Invoice")
		.where(invoice.invoice_type == "Billable")
		.where(invoice.status.notin(("Cancelled", "Waived")))
		.where(server.atlas_host_id.isnotnull())
		.groupby(server.atlas_host_id, invoice.currency)
	).run(as_dict=True)
	earned = defaultdict(float)
	for row in rows:
		earned[row.atlas_host_id] += flt(to_inr(row.amount, row.currency))
	return earned


def _row(machine, incidents: list, earned: float) -> dict:
	since = getdate(machine.deployed_on or machine.creation)
	months = max(date_diff(getdate(), since) / 30.4, 0)
	purchase = flt(machine.purchase_price_inr) if machine.ownership == "Owned" else 0.0
	running = flt(machine.cost_per_month_inr) * months
	repairs = sum(flt(i.repair_cost_inr) for i in incidents)
	profit = earned - running - repairs
	invested = purchase + running + repairs
	monthly_profit = profit / months if months >= 1 else None
	return {
		"metal_server": machine.name,
		"region": machine.region,
		"model": machine.model,
		"ownership": _(machine.ownership or "Rented"),
		"inr": "INR",
		"in_service_since": since,
		"age_months": flt(months, 1),
		"purchase_price": purchase,
		"running_cost": running,
		"repair_cost": repairs,
		"incidents": len(incidents),
		"downtime_hours": flt(sum(flt(i.downtime_hours) for i in incidents), 1),
		"earned": earned,
		"gross_profit": profit,
		"payback_months": flt(purchase / monthly_profit, 1)
		if purchase and monthly_profit and monthly_profit > 0
		else None,
		"roi_percent": flt(100 * (profit - purchase) / invested, 1) if invested else None,
		"warranty": _warranty(machine.warranty_until),
	}


def _warranty(until) -> str:
	if not until:
		return _("Not recorded")
	days = date_diff(until, getdate())
	return _("Expired") if days < 0 else _("{0} days left").format(days)


def _message(rows: list[dict]) -> str:
	text = _(
		"Running cost is the monthly cost times the months in service. ROI is gross profit less the purchase price, over all money put in. Payback is the purchase price over the average monthly gross profit."
	)
	if any(row["ownership"] == _("Owned") and not row["purchase_price"] for row in rows):
		text += " " + _("Some owned machines have no purchase price.")
	return text


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["metal_server"] for row in rows],
			"datasets": [
				{"name": _("Earned"), "values": [flt(row["earned"], 2) for row in rows]},
				{
					"name": _("Cost to Date"),
					"values": [
						flt(row["running_cost"] + row["repair_cost"] + row["purchase_price"], 2)
						for row in rows
					],
				},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	earned = sum(row["earned"] for row in rows)
	cost = sum(row["running_cost"] + row["repair_cost"] + row["purchase_price"] for row in rows)
	return [
		{"label": _("Machines"), "value": len(rows), "datatype": "Int"},
		{"label": _("Earned to Date (INR)"), "value": earned, "datatype": "Currency", "currency": "INR"},
		{"label": _("Cost to Date (INR)"), "value": cost, "datatype": "Currency", "currency": "INR"},
		{
			"label": _("Paid Back"),
			"value": sum(
				1
				for row in rows
				if row["earned"] >= row["running_cost"] + row["repair_cost"] + row["purchase_price"]
			),
			"datatype": "Int",
			"indicator": "Green",
		},
	]


def get_columns() -> list[dict]:
	return [
		column(_("Metal Server"), "metal_server", "Link", 140, options="Metal Server"),
		column(_("Model"), "model", "Data", 140),
		column(_("Ownership"), "ownership", "Data", 90),
		column(_("In Service Since"), "in_service_since", "Date", 120),
		column(_("Months"), "age_months", "Float", 80, precision=1),
		inr(_("Purchase Price (INR)"), "purchase_price", 140),
		inr(_("Running Cost to Date (INR)"), "running_cost", 170),
		inr(_("Repairs (INR)"), "repair_cost"),
		column(_("Incidents"), "incidents", "Int", 80),
		column(_("Hours Down"), "downtime_hours", "Float", 90, precision=1),
		inr(_("Earned to Date (INR)"), "earned", 150),
		inr(_("Gross Profit to Date (INR)"), "gross_profit", 170),
		column(_("Payback (Months)"), "payback_months", "Float", 120, precision=1),
		column(_("ROI %"), "roi_percent", "Percent", 80),
		column(_("Warranty"), "warranty", "Data", 110),
	]
