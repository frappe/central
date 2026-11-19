# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import math
from collections import Counter

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.catalog.composition import COMPUTE, DISK, MEMORY, composition_quantities
from central.billing.report._capacity import active_machines
from central.billing.report._columns import column

LIMITS = (("vcpus", "vCPU"), ("memory_gib", "Memory"), ("disk_gib", "Disk"))


def execute(filters: dict | None = None):
	"""How many servers of each plan fit on an empty machine of each model, and which resource stops it."""
	filters = filters or {}
	models = _models(active_machines(filters.get("region")))
	plans = frappe.get_all("Plan", filters={"is_active": 1}, fields=["name", "title"], order_by="title")
	shapes = _shapes([plan.name for plan in plans])
	current = _current_counts()
	rows = []
	for model, capacity in models.items():
		for plan in plans:
			if plan.name in shapes:
				rows.append(
					_row(model, capacity, plan, shapes[plan.name], current.get((model, plan.name), 0))
				)
	return get_columns(), rows, _message(), None, _summary(rows)


def _models(machines: list) -> dict[str, dict]:
	"""Sellable capacity of one machine per model. A machine with no model is its own model."""
	models = {}
	for machine in machines:
		key = machine.model or _("{0} ({1} vCPU)").format(machine.name, machine.vcpus)
		models.setdefault(
			key,
			{
				"machines": 0,
				"vcpus": (flt(machine.vcpus) - flt(machine.reserved_vcpus))
				* (flt(machine.cpu_overcommit_ratio) or 1),
				"memory_gib": flt(machine.memory_gib) - flt(machine.reserved_memory_gib),
				"disk_gib": flt(machine.disk_gib) - flt(machine.reserved_disk_gib),
			},
		)
		models[key]["machines"] += 1
	return models


def _shapes(plans: list[str]) -> dict[str, dict]:
	"""vCPUs, memory and disk each plan bundles, read in one query. A plan with no compute is not a server plan."""
	includes = {}
	for row in frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": ["in", plans]},
		fields=["parent", "resource_type", "quantity"],
	):
		includes.setdefault(row.parent, []).append(row)
	shapes = {}
	for plan, rows in includes.items():
		quantities = composition_quantities(rows)
		if quantities.get(COMPUTE):
			shapes[plan] = {
				"vcpus": flt(quantities[COMPUTE]),
				"memory_gib": flt(quantities.get(MEMORY)),
				"disk_gib": flt(quantities.get(DISK)),
			}
	return shapes


def _current_counts() -> Counter:
	"""Live servers per (model, plan), through the host each server runs on."""
	model_of = {
		row.atlas_host_id: row.model or _("{0} ({1} vCPU)").format(row.name, row.vcpus)
		for row in frappe.get_all(
			"Metal Server", filters={"status": "Active"}, fields=["name", "model", "vcpus", "atlas_host_id"]
		)
		if row.atlas_host_id
	}
	counts = Counter()
	for server in frappe.get_all(
		"Virtual Machine",
		filters={"status": ["not in", ("Terminated", "Failed")], "atlas_host_id": ["is", "set"]},
		fields=["plan", "atlas_host_id"],
	):
		if server.atlas_host_id in model_of:
			counts[(model_of[server.atlas_host_id], server.plan)] += 1
	return counts


def _row(model: str, capacity: dict, plan, shape: dict, current: int) -> dict:
	fits = {
		label: (math.floor(capacity[field] / shape[field]) if shape[field] else None)
		for field, label in LIMITS
	}
	limits = {label: count for label, count in fits.items() if count is not None}
	binding = min(limits, key=limits.get)
	return {
		"model": model,
		"machines": capacity["machines"],
		"plan": plan.name,
		"title": plan.title,
		"plan_vcpus": shape["vcpus"],
		"plan_memory_gib": flt(shape["memory_gib"], 1),
		"plan_disk_gib": shape["disk_gib"],
		"fit_by_vcpu": fits["vCPU"],
		"fit_by_memory": fits["Memory"],
		"fit_by_disk": fits["Disk"],
		"max_per_machine": limits[binding],
		"binding": _(binding),
		"current": current,
	}


def _message() -> str:
	return _(
		"Each row is one machine of the model, empty, filled with one plan only. Sellable capacity takes off the host reserve and applies the CPU overcommit ratio. Current counts live servers of the plan on machines of the model."
	)


def _summary(rows: list[dict]) -> list[dict]:
	bindings = Counter(row["binding"] for row in rows)
	return [
		{"label": _("Machine Models"), "value": len({row["model"] for row in rows}), "datatype": "Int"},
		{"label": _("Plans"), "value": len({row["plan"] for row in rows}), "datatype": "Int"},
		{
			"label": _("Most Plans Run Out Of"),
			"value": bindings.most_common(1)[0][0] if bindings else "",
			"datatype": "Data",
			"indicator": "Orange",
		},
	]


def get_columns() -> list[dict]:
	return [
		column(_("Model"), "model", "Data", 180),
		column(_("Machines"), "machines", "Int", 80),
		column(_("Plan"), "plan", "Link", 110, options="Plan"),
		column(_("Title"), "title", "Data", 170),
		column(_("Plan vCPUs"), "plan_vcpus", "Float", 90, precision=1),
		column(_("Plan Memory (GiB)"), "plan_memory_gib", "Float", 130, precision=1),
		column(_("Plan Disk (GiB)"), "plan_disk_gib", "Float", 110, precision=0),
		column(_("Fit by vCPU"), "fit_by_vcpu", "Int", 90),
		column(_("Fit by Memory"), "fit_by_memory", "Int", 100),
		column(_("Fit by Disk"), "fit_by_disk", "Int", 90),
		column(_("Most per Machine"), "max_per_machine", "Int", 120),
		column(_("Limited By"), "binding", "Data", 100),
		column(_("Running Now"), "current", "Int", 100),
	]
