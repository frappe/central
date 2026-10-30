# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.report._inventory import Inventory


def execute(filters: dict | None = None):
	"""Bare metal capacity per region against what live servers hold, and what the idle part costs."""
	rows = Inventory(filters).regions()
	return get_columns(), rows, get_message(rows), get_chart(rows), get_summary(rows)


def get_message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No bare metal and no live servers.")

	unpriced = [row["region"] for row in rows if row["servers"] and not row["cost"]]
	if unpriced:
		return _("{0} run servers with no active Metal Server, so their cost reads 0.").format(
			", ".join(frappe.bold(region) for region in unpriced)
		)
	return None


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	return {
		"data": {
			"labels": [row["region"] for row in rows],
			"datasets": [
				{"name": _("Allocated vCPUs"), "values": [row["allocated_vcpus"] for row in rows]},
				{
					"name": _("Free vCPUs"),
					"values": [max(row["vcpus"] - row["allocated_vcpus"], 0) for row in rows],
				},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def get_summary(rows: list[dict]) -> list[dict]:
	vcpus = sum(row["vcpus"] for row in rows)
	allocated = sum(row["allocated_vcpus"] for row in rows)
	used = round(100 * allocated / vcpus, 1) if vcpus else 0
	return [
		{"label": _("Metal Servers"), "value": sum(row["metal_servers"] for row in rows), "datatype": "Int"},
		{"label": _("vCPUs Used"), "value": f"{used}%", "datatype": "Data", "indicator": _indicator(used)},
		{
			"label": _("Metal Cost (INR)"),
			"value": sum(row["cost"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
		},
		{
			"label": _("Idle Cost (INR)"),
			"value": sum(row["idle_cost"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Red",
		},
	]


def _indicator(used_percent: float) -> str:
	# Above 85% a region has little room for new servers; below 40% the metal mostly sits idle.
	if used_percent > 85:
		return "Red"
	return "Green" if used_percent >= 40 else "Orange"


def get_columns() -> list[dict]:
	return [
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Link", "options": "Region", "width": 120},
		{"label": _("Metal Servers"), "fieldname": "metal_servers", "fieldtype": "Int", "width": 110},
		{"label": _("Live Servers"), "fieldname": "servers", "fieldtype": "Int", "width": 100},
		{"label": _("vCPUs"), "fieldname": "vcpus", "fieldtype": "Float", "precision": 0, "width": 80},
		{
			"label": _("Allocated vCPUs"),
			"fieldname": "allocated_vcpus",
			"fieldtype": "Float",
			"precision": 2,
			"width": 120,
		},
		{"label": _("vCPU Used %"), "fieldname": "vcpu_used_percent", "fieldtype": "Percent", "width": 100},
		{
			"label": _("Memory (GiB)"),
			"fieldname": "memory_gib",
			"fieldtype": "Float",
			"precision": 0,
			"width": 110,
		},
		{
			"label": _("Allocated Memory (GiB)"),
			"fieldname": "allocated_memory_gib",
			"fieldtype": "Float",
			"precision": 1,
			"width": 160,
		},
		{
			"label": _("Memory Used %"),
			"fieldname": "memory_used_percent",
			"fieldtype": "Percent",
			"width": 110,
		},
		{
			"label": _("Disk (GiB)"),
			"fieldname": "disk_gib",
			"fieldtype": "Float",
			"precision": 0,
			"width": 100,
		},
		{
			"label": _("Allocated Disk (GiB)"),
			"fieldname": "allocated_disk_gib",
			"fieldtype": "Float",
			"precision": 0,
			"width": 150,
		},
		{"label": _("Disk Used %"), "fieldname": "disk_used_percent", "fieldtype": "Percent", "width": 100},
		{
			"label": _("Metal Cost (INR)"),
			"fieldname": "cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Cost per vCPU (INR)"),
			"fieldname": "cost_per_vcpu",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"label": _("Idle Cost (INR)"),
			"fieldname": "idle_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
	]
