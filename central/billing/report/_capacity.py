# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe.utils import flt

from central.billing.report._inventory import Inventory
from central.billing.report._telemetry import Telemetry

RESOURCES = (
	("vCPU", "vcpus", "reserved_vcpus", "allocated_vcpus"),
	("Memory (GiB)", "memory_gib", "reserved_memory_gib", "allocated_memory_gib"),
	("Disk (GiB)", "disk_gib", "reserved_disk_gib", "allocated_disk_gib"),
)


class Fleet:
	"""Every active machine with its capacity per resource: physical, reserved, sellable, allocated and used.

	Allocated is what Atlas reports for the host, platform VMs included, when telemetry answers.
	Otherwise it is the sum of Central's servers placed on the host. Used is the host's own
	measured CPU and memory."""

	def __init__(self, filters: dict | None = None):
		self.filters = filters or {}
		self.inventory = Inventory(self.filters)
		self.telemetry = Telemetry()
		self.machines = active_machines(self.filters.get("region"))
		self.servers_by_host = defaultdict(list)
		for server in self.inventory.servers:
			if server.atlas_host_id:
				self.servers_by_host[server.atlas_host_id].append(server)
		self.host_usage = self.telemetry.hosts(self.machines)

	def capacity(self, machine) -> dict[str, dict]:
		"""Resource label -> physical, reserved, sellable, allocated, platform, used, remaining."""
		servers = self.servers_by_host.get(machine.atlas_host_id, [])
		host = self.host_usage.get(machine.atlas_host_id) or {}
		central = {
			"vcpus": sum(s.vcpus for s in servers),
			"memory_gib": sum(s.memory_gib for s in servers),
			"disk_gib": sum(s.disk_gib for s in servers),
		}
		used = {"vcpus": _used_vcpus(machine, host), "memory_gib": host.get("memory_used_gib")}
		sellable = sellable_capacity(machine)

		out = {}
		for label, physical_field, reserved_field, allocated_field in RESOURCES:
			allocated = max(flt(host.get(allocated_field)), central[physical_field])
			out[label] = {
				"physical": flt(machine.get(physical_field)),
				"reserved": flt(machine.get(reserved_field)),
				"sellable": sellable[physical_field],
				"allocated": allocated,
				"platform": max(allocated - central[physical_field], 0),
				"used": used.get(physical_field),
				"remaining": max(sellable[physical_field] - allocated, 0),
			}
		return out

	@property
	def gaps(self) -> list[str]:
		return sorted(set(self.telemetry.gaps))


def sellable_capacity(machine) -> dict[str, float]:
	"""Sellable vCPUs, memory and disk of a machine: physical less the host reserve, with vCPUs overcommitted."""
	sellable = {
		physical_field: flt(machine.get(physical_field)) - flt(machine.get(reserved_field))
		for _label, physical_field, reserved_field, _allocated_field in RESOURCES
	}
	sellable["vcpus"] *= flt(machine.cpu_overcommit_ratio) or 1
	return sellable


def _used_vcpus(machine, host: dict) -> float | None:
	if host.get("cpu_percent") is None:
		return None
	return flt(machine.vcpus) * flt(host["cpu_percent"]) / 100


def active_machines(region: str | None) -> list:
	filters = {"status": "Active"}
	if region:
		filters["region"] = region
	return frappe.get_all(
		"Metal Server",
		filters=filters,
		fields=[
			"name",
			"region",
			"model",
			"vendor",
			"ownership",
			"atlas_host_id",
			"cost_per_month_inr",
			"vcpus",
			"memory_gib",
			"disk_gib",
			"reserved_vcpus",
			"reserved_memory_gib",
			"reserved_disk_gib",
			"cpu_overcommit_ratio",
			"purchase_price_inr",
			"purchased_on",
			"deployed_on",
			"warranty_until",
			"creation",
		],
		order_by="region, name",
	)


def component_rates_inr(region: str | None = None) -> dict[str, float]:
	"""INR price per vCPU, GiB of memory and GiB of disk a month, from the component rate card."""
	from central.billing.catalog.pricing import resolve_component_rate

	rates = {}
	for label, resource_type in (("vCPU", "Compute"), ("Memory (GiB)", "Memory"), ("Disk (GiB)", "Disk")):
		if frappe.db.exists("Resource Type", resource_type):
			rates[label] = flt(resolve_component_rate(resource_type, "INR", region))
	return rates
