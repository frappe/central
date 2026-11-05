# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._capacity import Fleet, component_rates_inr
from central.billing.report._columns import column, inr


def execute(filters: dict | None = None):
	"""What stops us selling more: the resource each machine runs out of first, and what the rest strands.

	The binding resource is the one with the highest allocated share. When it fills up, the
	other resources can only fill to the same share; the gap is stranded, and is priced at the
	component rate card."""
	filters = filters or {}
	fleet = Fleet(filters)
	rates = component_rates_inr(filters.get("region"))
	rows = [_row(machine, fleet.capacity(machine), rates) for machine in fleet.machines]
	return get_columns(), rows, _message(fleet, rates), _chart(rows), _summary(rows)


def _row(machine, capacity: dict, rates: dict) -> dict:
	shares = {
		resource: flt(numbers["allocated"]) / flt(numbers["sellable"]) if flt(numbers["sellable"]) else 0
		for resource, numbers in capacity.items()
	}
	binding = max(shares, key=shares.get)
	row = {
		"metal_server": machine.name,
		"region": machine.region,
		"model": machine.model,
		"binding": binding if shares[binding] else None,
		"binding_percent": flt(100 * shares[binding], 1),
		"inr": "INR",
		"stranded_revenue": 0.0,
	}
	for resource, numbers in capacity.items():
		key = _key(resource)
		# At the moment the binding resource is full, this one is filled to its own share of the binding one.
		filled = shares[resource] / shares[binding] if shares[binding] else 0
		stranded = flt(numbers["sellable"]) * (1 - filled) if shares[binding] else 0
		row[f"{key}_stranded_percent"] = flt(100 * (1 - filled), 1) if shares[binding] else 0
		row[f"{key}_stranded"] = flt(stranded, 1)
		row["stranded_revenue"] += stranded * flt(rates.get(resource))
	return row


def _key(resource: str) -> str:
	return {"vCPU": "vcpu", "Memory (GiB)": "memory", "Disk (GiB)": "disk"}[resource]


def _message(fleet: Fleet, rates: dict) -> str:
	text = _(
		"Stranded capacity is what cannot be sold once the binding resource is full, at today's server mix. It is priced at the component rate card per month."
	)
	if not any(rates.values()):
		text += " " + _("The component rate card has no INR rates, so stranded revenue reads 0.")
	if fleet.gaps:
		text += " " + _("No telemetry for: {0}, so platform servers are not counted.").format(
			", ".join(fleet.gaps)
		)
	return text


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["metal_server"] for row in rows],
			"datasets": [
				{"name": _("vCPU stranded %"), "values": [row["vcpu_stranded_percent"] for row in rows]},
				{"name": _("Memory stranded %"), "values": [row["memory_stranded_percent"] for row in rows]},
				{"name": _("Disk stranded %"), "values": [row["disk_stranded_percent"] for row in rows]},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	bindings = [row["binding"] for row in rows if row["binding"]]
	most = max(set(bindings), key=bindings.count) if bindings else _("None yet")
	return [
		{"label": _("Fleet Runs Out of First"), "value": _(most), "datatype": "Data", "indicator": "Orange"},
		{
			"label": _("Stranded Revenue per Month (INR)"),
			"value": sum(row["stranded_revenue"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Red",
		},
	]


def get_columns() -> list[dict]:
	return [
		column(_("Metal Server"), "metal_server", "Link", 150, options="Metal Server"),
		column(_("Region"), "region", "Link", 100, options="Region"),
		column(_("Model"), "model", "Data", 140),
		column(_("Runs Out First"), "binding", "Data", 120),
		column(_("Its Allocated %"), "binding_percent", "Percent", 110),
		column(_("vCPU Stranded %"), "vcpu_stranded_percent", "Percent", 120),
		column(_("Memory Stranded %"), "memory_stranded_percent", "Percent", 130),
		column(_("Disk Stranded %"), "disk_stranded_percent", "Percent", 120),
		column(_("Memory Stranded (GiB)"), "memory_stranded", "Float", 150, precision=0),
		column(_("Disk Stranded (GiB)"), "disk_stranded", "Float", 130, precision=0),
		inr(_("Stranded Revenue per Month (INR)"), "stranded_revenue", 200),
	]
