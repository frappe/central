# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Max, Min, Sum
from frappe.utils import add_days, cint, date_diff, flt, getdate

from central.billing.report._capacity import Fleet
from central.billing.report._columns import column

LOOKBACK_DAYS = 90
FIELDS = (
	("vCPU", "vcpus", 1),
	("Memory (GiB)", "memory_megabytes", 1 / 1024),
	("Disk (GiB)", "disk_gigabytes", 1),
)


def execute(filters: dict | None = None):
	"""When to buy the next machine, and what shape: remaining capacity against 90 days of growth.

	Growth is the change in what Central's servers hold over the last 90 days. Platform servers
	are counted in what is allocated today but assumed flat."""
	filters = filters or {}
	fleet = Fleet(filters)
	lead_days = cint(filters.get("lead_days")) or 45
	today = getdate()
	then = add_days(today, -LOOKBACK_DAYS)

	rows = []
	for region in sorted({machine.region for machine in fleet.machines}):
		machines = [m for m in fleet.machines if m.region == region]
		capacity = _region_capacity(fleet, machines)
		months = _months_observed(region, then, today)
		growth = {
			label: _held(region, today, field) - _held(region, then, field) for label, field, _scale in FIELDS
		}
		for label, _field, scale in FIELDS:
			rows.append(
				_row(region, label, capacity[label], growth[label] * scale / months, today, lead_days)
			)
		_recommend(rows[-3:], machines, growth)
	return get_columns(), rows, _message(lead_days), None, _summary(rows)


def _region_capacity(fleet: Fleet, machines: list) -> dict[str, dict]:
	total: dict = {}
	for machine in machines:
		for label, numbers in fleet.capacity(machine).items():
			bucket = total.setdefault(label, {"sellable": 0.0, "allocated": 0.0})
			bucket["sellable"] += numbers["sellable"]
			bucket["allocated"] += numbers["allocated"]
	return total


def _held(region: str, on, field: str) -> float:
	"""What Central's servers in the region held on a date: created by then, not yet terminated."""
	server = frappe.qb.DocType("Virtual Machine")
	change = frappe.qb.DocType("Subscription Change")
	subscription = frappe.qb.DocType("Subscription")
	ended = (
		frappe.qb.from_(change)
		.join(subscription)
		.on(subscription.name == change.subscription)
		.select(Max(change.effective_at))
		.where(subscription.server_id == server.name)
		.where(change.change_type == "Cancelled")
	)
	query = (
		frappe.qb.from_(server)
		.select(Sum(server[field]))
		.where(server.region == region)
		.where(server.creation <= f"{on} 23:59:59")
		.where(
			server.status.notin(("Terminated", "Failed"))
			| (Coalesce(ended, server.modified) > f"{on} 23:59:59")
		)
	)
	return flt(query.run()[0][0])


def _months_observed(region: str, then, today) -> float:
	"""Months of history behind the growth: 90 days, or less for a region younger than that."""
	server = frappe.qb.DocType("Virtual Machine")
	first = frappe.qb.from_(server).select(Min(server.creation)).where(server.region == region).run()[0][0]
	start = max(getdate(first), then) if first else then
	return max(date_diff(today, start), 1) / 30.4


def _row(region: str, resource: str, capacity: dict, per_month: float, today, lead_days: int) -> dict:
	remaining = max(capacity["sellable"] - capacity["allocated"], 0)
	months = flt(remaining / per_month, 1) if per_month > 0 else None
	runs_out = add_days(today, int(months * 30.4)) if months is not None else None
	return {
		"region": region,
		"resource": resource,
		"sellable": flt(capacity["sellable"], 0),
		"allocated": flt(capacity["allocated"], 1),
		"remaining": flt(remaining, 1),
		"growth_per_month": flt(per_month, 2),
		"months_left": months,
		"runs_out_on": runs_out,
		"buy_by": add_days(runs_out, -lead_days) if runs_out else None,
		"recommendation": None,
	}


def _recommend(region_rows: list[dict], machines: list, growth: dict) -> None:
	"""Name the machine shape that matches how the region grows: memory per vCPU of new demand."""
	vcpu_growth = growth["vCPU"]
	memory_growth = growth["Memory (GiB)"] / 1024
	if vcpu_growth <= 0:
		return
	wanted = memory_growth / vcpu_growth
	best = min(machines, key=lambda m: abs(flt(m.memory_gib) / (flt(m.vcpus) or 1) - wanted), default=None)
	first = min(
		(r for r in region_rows if r["months_left"] is not None), key=lambda r: r["months_left"], default=None
	)
	if best and first:
		first["recommendation"] = _(
			"Runs out of {0} first. New demand takes {1} GiB per vCPU; closest machine: {2} ({3} vCPU, {4} GiB)."
		).format(_(first["resource"]), flt(wanted, 1), best.model or best.name, best.vcpus, best.memory_gib)


def _message(lead_days: int) -> str:
	return _(
		"Growth is what Central's servers held 90 days ago (or since the region's first server) against today, per month. Buy-by is the run-out date less {0} days to buy and install. A resource that did not grow has no run-out date."
	).format(lead_days)


def _summary(rows: list[dict]) -> list[dict]:
	dated = [row for row in rows if row["buy_by"]]
	first = min(dated, key=lambda row: row["buy_by"], default=None)
	return [
		{
			"label": _("Next Buy-By Date"),
			"value": str(first["buy_by"]) if first else _("No growth yet"),
			"datatype": "Data",
			"indicator": "Orange",
		},
		{"label": _("Region"), "value": first["region"] if first else "", "datatype": "Data"},
		{"label": _("Runs Out Of"), "value": _(first["resource"]) if first else "", "datatype": "Data"},
	]


def get_columns() -> list[dict]:
	return [
		column(_("Region"), "region", "Link", 100, options="Region"),
		column(_("Resource"), "resource", "Data", 110),
		column(_("Sellable"), "sellable", "Float", 90, precision=0),
		column(_("Allocated"), "allocated", "Float", 90, precision=1),
		column(_("Remaining"), "remaining", "Float", 100, precision=1),
		column(_("Growth per Month"), "growth_per_month", "Float", 130, precision=2),
		column(_("Months Left"), "months_left", "Float", 100, precision=1),
		column(_("Runs Out On"), "runs_out_on", "Date", 110),
		column(_("Buy By"), "buy_by", "Date", 100),
		column(_("Recommendation"), "recommendation", "Data", 420),
	]
