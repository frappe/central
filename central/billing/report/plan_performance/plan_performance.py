# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._columns import column, inr
from central.billing.report._economics import to_inr
from central.billing.report._inventory import PAID, Inventory
from central.billing.report._telemetry import Telemetry

SCARCE = {"vcpus": "vCPU", "memory_gib": "GiB of memory", "disk_gib": "GiB of disk"}


def execute(filters: dict | None = None):
	"""Which plans are best: servers, customers, MRR, bare metal cost, margin and use per plan.

	MRR counts paying customers only; list MRR counts every live server at its price. Revenue
	per scarce unit divides list MRR by the resource the fleet runs out of first."""
	filters = filters or {}
	inventory = Inventory(filters)
	usage = Telemetry().servers(inventory.servers)
	scarce = _scarce_resource(inventory)
	titles = dict(frappe.get_all("Plan", fields=["name", "title"], as_list=True))

	groups: dict = {}
	for server in inventory.servers:
		row = groups.setdefault(server.plan or _("No plan"), _empty(server, titles))
		_add(row, server, usage.get(server.name))
	rows = [_finish(row, scarce) for row in groups.values()]
	rows.sort(key=lambda row: row["list_mrr"], reverse=True)
	return get_columns(scarce), rows, _message(scarce), _chart(rows), _summary(rows)


def _scarce_resource(inventory: Inventory) -> str:
	"""The resource with the highest allocated share across all regions."""
	regions = inventory.regions()
	shares = {
		field: sum(r[f"allocated_{field}"] for r in regions) / (sum(r[field] for r in regions) or 1)
		for field in ("vcpus", "memory_gib", "disk_gib")
	}
	return max(shares, key=shares.get)


def _empty(server, titles: dict) -> dict:
	return {
		"plan": server.plan,
		"title": titles.get(server.plan),
		"inr": "INR",
		"servers": 0,
		"teams": set(),
		"paying_servers": 0,
		"mrr": 0.0,
		"list_mrr": 0.0,
		"cost": 0.0,
		"vcpus": 0.0,
		"memory_gib": 0.0,
		"disk_gib": 0.0,
		"cpu_samples": [],
	}


def _add(row: dict, server, measured: dict | None) -> None:
	list_inr = flt(to_inr(server.list_rate, server.currency))
	row["servers"] += 1
	row["teams"].add(server.team)
	row["list_mrr"] += list_inr
	row["cost"] += server.cost
	row["vcpus"] += server.vcpus
	row["memory_gib"] += server.memory_gib
	row["disk_gib"] += server.disk_gib
	if server.funding == PAID:
		row["paying_servers"] += 1
		row["mrr"] += list_inr
	if measured:
		row["cpu_samples"].append(measured["cpu_percent"])


def _finish(row: dict, scarce: str) -> dict:
	samples = row.pop("cpu_samples")
	row["customers"] = len(row.pop("teams"))
	row["margin"] = row["mrr"] - row["cost"]
	row["margin_percent"] = flt(100 * row["margin"] / row["mrr"], 1) if row["mrr"] else None
	row["cpu_used_percent"] = flt(sum(samples) / len(samples), 1) if samples else None
	row["mrr_per_vcpu"] = flt(row["list_mrr"] / row["vcpus"], 2) if row["vcpus"] else None
	row["mrr_per_scarce_unit"] = flt(row["list_mrr"] / row[scarce], 2) if row[scarce] else None
	return row


def _message(scarce: str) -> str:
	return _(
		"The fleet runs out of {0} first, so revenue per {0} says which plan earns most from what is scarce. Used CPU is the average over the last 7 days, for servers that run the Pilot agent."
	).format(_(SCARCE[scarce]))


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["title"] or row["plan"] or _("No plan") for row in rows[:15]],
			"datasets": [{"name": _("List MRR"), "values": [flt(row["list_mrr"], 2) for row in rows[:15]]}],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	best = max(rows, key=lambda row: row["mrr_per_scarce_unit"] or 0, default=None)
	return [
		{"label": _("Plans in Use"), "value": len(rows), "datatype": "Int"},
		{
			"label": _("Paying MRR (INR)"),
			"value": sum(row["mrr"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
		},
		{
			"label": _("List MRR (INR)"),
			"value": sum(row["list_mrr"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
		},
		{
			"label": _("Best Use of the Scarce Resource"),
			"value": (best["title"] or best["plan"]) if best else "",
			"datatype": "Data",
			"indicator": "Green",
		},
	]


def get_columns(scarce: str) -> list[dict]:
	return [
		column(_("Plan"), "plan", "Link", 120, options="Plan"),
		column(_("Title"), "title", "Data", 180),
		column(_("Servers"), "servers", "Int", 70),
		column(_("Customers"), "customers", "Int", 90),
		column(_("Paying Servers"), "paying_servers", "Int", 110),
		inr(_("Paying MRR (INR)"), "mrr"),
		inr(_("List MRR (INR)"), "list_mrr"),
		inr(_("Bare Metal Cost (INR)"), "cost", 140),
		inr(_("Margin (INR)"), "margin"),
		column(_("Margin %"), "margin_percent", "Percent", 80),
		column(_("CPU Used %"), "cpu_used_percent", "Percent", 90),
		column(_("List MRR per vCPU (INR)"), "mrr_per_vcpu", "Currency", 150, options="inr"),
		column(
			_("List MRR per {0} (INR)").format(_(SCARCE[scarce])),
			"mrr_per_scarce_unit",
			"Currency",
			190,
			options="inr",
		),
	]
