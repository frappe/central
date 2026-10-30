# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._capacity import Fleet
from central.billing.report._columns import column


def execute(filters: dict | None = None):
	"""How full each machine really is: physical, sellable, allocated, used and remaining, per resource."""
	filters = filters or {}
	fleet = Fleet(filters)
	rows = []
	for machine in fleet.machines:
		if filters.get("metal_server") and machine.name != filters["metal_server"]:
			continue
		for resource, numbers in fleet.capacity(machine).items():
			rows.append(_row(machine, resource, numbers))
	return get_columns(), rows, _message(fleet), _chart(rows), _summary(rows)


def _row(machine, resource: str, numbers: dict) -> dict:
	sellable = numbers["sellable"]
	used = numbers["used"]
	return {
		"metal_server": machine.name,
		"region": machine.region,
		"resource": resource,
		**numbers,
		"allocated_percent": _percent(numbers["allocated"], sellable),
		"used_percent": None if used is None else _percent(used, sellable),
	}


def _percent(part, whole) -> float:
	return flt(100 * flt(part) / flt(whole), 1) if flt(whole) else 0.0


def _message(fleet: Fleet) -> str:
	text = _(
		"Allocated includes Atlas's own platform servers (proxy, services) when telemetry answers. Used is measured on the host: memory used includes the host's own cache, so it can exceed what is allocated. Disk use is not measured yet."
	)
	if fleet.gaps:
		text += " " + _("No telemetry for: {0}. Set the Telemetry Data Source on the region.").format(
			", ".join(fleet.gaps)
		)
	if any(not machine.atlas_host_id for machine in fleet.machines):
		text += " " + _("Some machines have no Atlas host ID, so their allocation counts no Central server.")
	return text


def _chart(rows: list[dict]) -> dict | None:
	vcpu = [row for row in rows if row["resource"] == "vCPU"]
	if not vcpu:
		return None
	return {
		"data": {
			"labels": [row["metal_server"] for row in vcpu],
			"datasets": [
				{"name": _("Allocated vCPUs"), "values": [flt(row["allocated"], 1) for row in vcpu]},
				{"name": _("Remaining vCPUs"), "values": [flt(row["remaining"], 1) for row in vcpu]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def _summary(rows: list[dict]) -> list[dict]:
	summary = []
	for resource in ("vCPU", "Memory (GiB)", "Disk (GiB)"):
		these = [row for row in rows if row["resource"] == resource]
		sellable = sum(row["sellable"] for row in these)
		allocated = sum(row["allocated"] for row in these)
		summary.append(
			{
				"label": _("{0} Allocated").format(_(resource)),
				"value": f"{_percent(allocated, sellable)}% of {flt(sellable, 0):,.0f}",
				"datatype": "Data",
			}
		)
	return summary


def get_columns() -> list[dict]:
	return [
		column(_("Metal Server"), "metal_server", "Link", 150, options="Metal Server"),
		column(_("Region"), "region", "Link", 100, options="Region"),
		column(_("Resource"), "resource", "Data", 110),
		column(_("Physical"), "physical", "Float", 90, precision=0),
		column(_("Reserved by Host"), "reserved", "Float", 120, precision=0),
		column(_("Sellable"), "sellable", "Float", 90, precision=0),
		column(_("Allocated"), "allocated", "Float", 90, precision=1),
		column(_("Of Which Platform"), "platform", "Float", 120, precision=1),
		column(_("Allocated %"), "allocated_percent", "Percent", 100),
		column(_("Used"), "used", "Float", 80, precision=1),
		column(_("Used %"), "used_percent", "Percent", 80),
		column(_("Remaining"), "remaining", "Float", 100, precision=1),
	]
