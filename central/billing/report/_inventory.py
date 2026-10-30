# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt

from central.billing import settings
from central.billing.catalog.subscriptions import active_segments

# A server holds region capacity until it is gone for good.
RELEASED_STATUSES = ("Terminated", "Failed")

INTERNAL = "Our Own Team"
TRIAL = "Free Trial"
PAID = "Paying Customer"
FREE_CREDITS = "Not Paying Yet"
IDLE = "Idle Capacity"
FUNDING_CLASSES = (INTERNAL, TRIAL, PAID, FREE_CREDITS)

# Credit a customer bought with money, as against promotional credit.
PURCHASED_CREDIT = ("Top-up", "Payment Method")
TRIAL_STATES = ("Active", "Ended", "Deleted")


class Inventory:
	"""The live servers of every region, who funds each one, and its share of the bare metal cost.

	A region's monthly metal cost is split by vCPU: each server carries its vCPUs times the
	region's cost per vCPU. Only a Paid server earns cash; the others run at no charge."""

	def __init__(self, filters: dict | None = None):
		self.filters = filters or {}
		self.capacity = region_capacity(self.filters.get("region"))
		self.servers = self._load_servers()

	def regions(self) -> list[dict]:
		"""Capacity, use and cost per region, with every region that has metal or servers."""
		names = sorted(set(self.capacity) | {server.region for server in self.servers})
		return [self._region_row(name) for name in names]

	def idle_rows(self) -> list[dict]:
		"""What each region's unused vCPUs cost, so allocated and idle add up to the metal bill."""
		rows = []
		for region in self.regions():
			idle_vcpus = max(region["vcpus"] - region["allocated_vcpus"], 0)
			if idle_vcpus:
				rows.append({"region": region["region"], "vcpus": idle_vcpus, "cost": region["idle_cost"]})
		return rows

	def _region_row(self, name: str) -> dict:
		capacity = self.capacity.get(name) or frappe._dict(
			metal_servers=0, vcpus=0, memory_gib=0, disk_gib=0, cost=0
		)
		servers = [server for server in self.servers if server.region == name]
		allocated_vcpus = sum(server.vcpus for server in servers)
		allocated_memory = sum(server.memory_gib for server in servers)
		allocated_disk = sum(server.disk_gib for server in servers)
		allocated_cost = sum(server.cost for server in servers)
		return {
			"region": name,
			"currency": "INR",
			"metal_servers": capacity.metal_servers,
			"servers": len(servers),
			"vcpus": capacity.vcpus,
			"allocated_vcpus": allocated_vcpus,
			"vcpu_used_percent": _percent(allocated_vcpus, capacity.vcpus),
			"memory_gib": capacity.memory_gib,
			"allocated_memory_gib": allocated_memory,
			"memory_used_percent": _percent(allocated_memory, capacity.memory_gib),
			"disk_gib": capacity.disk_gib,
			"allocated_disk_gib": allocated_disk,
			"disk_used_percent": _percent(allocated_disk, capacity.disk_gib),
			"cost": capacity.cost,
			"cost_per_vcpu": cost_per_vcpu(capacity),
			"allocated_cost": allocated_cost,
			"idle_cost": max(flt(capacity.cost) - allocated_cost, 0),
		}

	def _load_servers(self) -> list:
		servers = frappe.get_all(
			"Virtual Machine",
			filters=self._server_filters(),
			fields=[
				"name",
				"title",
				"team",
				"region",
				"status",
				"plan",
				"vcpus",
				"memory_megabytes",
				"disk_gigabytes",
				"atlas_host_id",
			],
			order_by="region, team, name",
		)
		if not servers:
			return []

		names = [server.name for server in servers]
		teams = list({server.team for server in servers})
		funding = Funding(teams, names)
		segments = _segments_by_server(names)
		team_names = dict(
			frappe.get_all(
				"Team", filters={"name": ["in", teams]}, fields=["name", "team_name"], as_list=True
			)
		)

		for server in servers:
			self._price(server, funding, segments.get(server.name), team_names)
		return servers

	def _server_filters(self) -> dict:
		filters = {"status": ["not in", RELEASED_STATUSES]}
		for fieldname in ("region", "team"):
			if self.filters.get(fieldname):
				filters[fieldname] = self.filters[fieldname]
		return filters

	def _price(self, server, funding: "Funding", segment, team_names: dict) -> None:
		server.team_name = team_names.get(server.team)
		server.vcpus = flt(server.vcpus)
		server.memory_gib = flt(server.memory_megabytes) / 1024
		server.disk_gib = flt(server.disk_gigabytes)
		server.funding = funding.of(server.team, server.name)
		server.cost = server.vcpus * cost_per_vcpu(self.capacity.get(server.region))
		server.currency = segment.currency if segment else None
		server.list_rate = flt(segment.locked_rate) if segment else 0
		server.revenue = server.list_rate if server.funding == PAID else 0
		server.revenue_inr = self.to_inr(server.revenue, server.currency)
		server.margin = None if server.revenue_inr is None else server.revenue_inr - server.cost

	def to_inr(self, amount: float, currency: str | None) -> float | None:
		"""`amount` in INR, or None when it is in another currency and no rate was given."""
		if not amount or currency in (None, "INR"):
			return flt(amount)
		rate = flt(self.filters.get(f"{currency.lower()}_to_inr"))
		if not rate and currency == "USD":
			rate = settings.reporting_usd_to_inr()
		return flt(amount) * rate if rate else None


class Funding:
	"""Who pays for a server: Our Own Team, then Free Trial, then Paying Customer, then Not Paying Yet. The first match wins."""

	def __init__(self, teams: list[str], servers: list[str]):
		self.internal = set(
			frappe.get_all("Tax Profile", filters={"team": ["in", teams], "is_internal": 1}, pluck="team")
		)
		self.paying = _paying_teams(teams)
		self.trial_servers = _trial_servers(servers)

	def of(self, team: str, server: str) -> str:
		if team in self.internal:
			return INTERNAL
		if server in self.trial_servers:
			return TRIAL
		if team in self.paying:
			return PAID
		return FREE_CREDITS


def region_capacity(region: str | None = None) -> dict:
	"""Active bare metal per region: machine count, vCPUs, memory, disk and monthly cost in INR."""
	metal = frappe.qb.DocType("Metal Server")
	query = (
		frappe.qb.from_(metal)
		.select(
			metal.region,
			Count(metal.name).as_("metal_servers"),
			Sum(metal.vcpus).as_("vcpus"),
			Sum(metal.memory_gib).as_("memory_gib"),
			Sum(metal.disk_gib).as_("disk_gib"),
			Sum(metal.cost_per_month_inr).as_("cost"),
		)
		.where(metal.status == "Active")
		.groupby(metal.region)
	)
	if region:
		query = query.where(metal.region == region)
	return {row.region: row for row in query.run(as_dict=True)}


def cost_per_vcpu(capacity) -> float:
	if not capacity or not flt(capacity.vcpus):
		return 0.0
	return flt(capacity.cost) / flt(capacity.vcpus)


def _segments_by_server(servers: list[str]) -> dict:
	return {
		segment.server_id: segment
		for segment in active_segments({"enabled": 1, "server_id": ["in", servers]})
	}


def _paying_teams(teams: list[str]) -> set[str]:
	"""Teams that pay with money: an active payment method, bought credit or a paid invoice."""
	with_method = frappe.get_all(
		"Payment Method", filters={"team": ["in", teams], "status": "Active"}, pluck="team"
	)
	bought = frappe.get_all(
		"Credit Ledger Entry",
		filters={"team": ["in", teams], "entry_type": "Credit", "reference_type": ["in", PURCHASED_CREDIT]},
		pluck="team",
	)
	paid = frappe.get_all("Invoice", filters={"team": ["in", teams], "amount_paid": [">", 0]}, pluck="team")
	return {*with_method, *bought, *paid}


def _trial_servers(servers: list[str]) -> set[str]:
	"""Servers billing defers for a free trial, read in two queries for the whole list."""
	sites = dict(
		frappe.get_all(
			"Site",
			filters={"server": ["in", servers], "trial_state": ["is", "set"]},
			fields=["server", "trial_state"],
			as_list=True,
		)
	)
	requested = set(
		frappe.get_all(
			"Resource Action",
			filters={"server": ["in", servers], "action": "create", "is_free_trial": 1},
			pluck="server",
		)
	)
	return {
		server
		for server in servers
		if sites.get(server) in TRIAL_STATES or (server not in sites and server in requested)
	}


def _percent(part: float, whole: float) -> float:
	return flt(100 * flt(part) / flt(whole), 1) if flt(whole) else 0.0
