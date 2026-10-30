# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._capacity import (
	RESOURCES,
	active_machines,
	component_rates_inr,
	sellable_capacity,
)
from central.billing.report._columns import column, inr
from central.billing.report._inventory import PAID, Inventory

# Rate card value the bare metal does not earn. Used Free is revenue we skip, not money we lose.
GAPS = (("unsold", "Unsold"), ("unpaid", "Used Free"), ("discount", "Discount"))


def execute(filters: dict | None = None):
	"""What the sellable bare metal could earn a month, and where it goes, per region or per machine.

	Potential revenue = unsold + used free + discount + cash revenue, so the four always add up."""
	filters = filters or {}
	group_by = filters.get("group_by") or "Region"
	book = YieldBook(filters)
	rows = book.by_metal_server() if group_by == "Metal Server" else book.by_region()
	return get_columns(group_by), rows, get_message(rows, book), get_chart(rows), get_summary(rows)


class YieldBook:
	"""Potential revenue of the sellable bare metal, split into unsold, used free, discount and cash.

	Potential prices every sellable vCPU, GiB of memory and GiB of disk at the region's component
	rate card. A live server holds its own resources at that price. Only a paying server earns
	cash, and the gap between its rate card value and what it pays is the discount. A server that
	pays nothing costs us its share of the metal bill, not its rate card value."""

	def __init__(self, filters: dict):
		self.inventory = Inventory(filters)
		self.machines = active_machines(filters.get("region"))
		self.rates: dict[str | None, dict] = {}

	def by_region(self) -> list[dict]:
		servers = self.inventory.servers
		regions = sorted({m.region for m in self.machines} | {s.region for s in servers})
		return [
			self._row(
				region,
				region,
				[m for m in self.machines if m.region == region],
				[s for s in servers if s.region == region],
			)
			for region in regions
		]

	def by_metal_server(self) -> list[dict]:
		hosts = {m.atlas_host_id for m in self.machines if m.atlas_host_id}
		servers = self.inventory.servers
		rows = [
			self._row(
				machine.name,
				machine.region,
				[machine],
				[s for s in servers if machine.atlas_host_id and s.atlas_host_id == machine.atlas_host_id],
			)
			for machine in self.machines
		]
		# A server on no known host earns against no machine, so it shows apart.
		unplaced = [s for s in servers if s.atlas_host_id not in hosts]
		if unplaced:
			rows.append(self._row(None, None, [], unplaced))
		return rows

	def has_missing_rates(self) -> bool:
		return any(not rates.get(label) for rates in self.rates.values() for label, *_fields in RESOURCES)

	def _row(self, group: str | None, region: str | None, machines: list, servers: list) -> dict:
		sellable = [sellable_capacity(m) for m in machines]
		usage = _usage(machines, sellable, servers)
		earnings = self._earnings(machines, sellable, servers)
		revenue = earnings["revenue"]
		return {
			"group": group,
			"region": region,
			"inr": "INR",
			"machines": len(machines),
			"servers": len(servers),
			**usage,
			**earnings,
			"yield_percent": _percent(revenue, earnings["potential"]),
			"revenue_per_sellable_vcpu": _ratio(revenue, usage["sellable_vcpus"]),
			"revenue_per_sold_vcpu": _ratio(revenue, usage["sold_vcpus"]),
		}

	def _earnings(self, machines: list, sellable: list[dict], servers: list) -> dict:
		paid = [s for s in servers if s.funding == PAID]
		potential = self._potential(machines, sellable)
		held = self._held(servers)
		paid_value = self._held(paid)
		revenue = _total([s.revenue_inr for s in paid])
		return {
			"unpaid_cost": _metal_cost(machines, [s for s in servers if s.funding != PAID]),
			"potential": potential,
			"unsold": potential - held,
			"unpaid": held - paid_value,
			"discount": None if revenue is None else paid_value - revenue,
			"revenue": revenue,
		}

	def _potential(self, machines: list, sellable: list[dict]) -> float:
		return sum(self._value(capacity, m.region) for capacity, m in zip(sellable, machines, strict=True))

	def _held(self, servers: list) -> float:
		return sum(self._value(s, s.region) for s in servers)

	def _value(self, resources, region: str | None) -> float:
		"""Rate card value a month of the vCPUs, memory and disk in `resources`."""
		if region not in self.rates:
			self.rates[region] = component_rates_inr(region)
		rates = self.rates[region]
		return sum(
			flt(resources.get(field)) * flt(rates.get(label))
			for label, field, _reserved, _allocated in RESOURCES
		)


def _usage(machines: list, sellable: list[dict], servers: list) -> dict:
	sellable_vcpus = sum(capacity["vcpus"] for capacity in sellable)
	sold_vcpus = sum(s.vcpus for s in servers)
	return {
		"sellable_vcpus": sellable_vcpus,
		"sold_vcpus": sold_vcpus,
		"vcpu_sold_percent": _percent(sold_vcpus, sellable_vcpus),
		"memory_sold_percent": _percent(
			sum(s.memory_gib for s in servers), sum(c["memory_gib"] for c in sellable)
		),
		"cost": sum(flt(m.cost_per_month_inr) for m in machines),
	}


def _metal_cost(machines: list, servers: list) -> float:
	"""Bare metal cost a month of `servers` by their vCPU share of `machines`.

	Servers on no machine carry their share of their region's metal bill."""
	machine_vcpus = sum(flt(m.vcpus) for m in machines)
	if not machine_vcpus:
		return sum(s.cost for s in servers)
	bill = sum(flt(m.cost_per_month_inr) for m in machines)
	return sum(s.vcpus for s in servers) * bill / machine_vcpus


def get_message(rows: list[dict], book: YieldBook) -> str | None:
	if not rows:
		return _("No bare metal or live servers match these filters.")

	notes = []
	if book.has_missing_rates():
		notes.append(_("The component rate card has no INR rate for some resources, so they count at 0."))
	if any(row["revenue"] is None for row in rows):
		notes.append(_("Some servers bill in USD. Enter a USD to INR rate to include them."))
	if any(row["machines"] == 0 and row["servers"] for row in rows):
		notes.append(_("Some servers run on no known machine, so they earn against no potential."))
	return " ".join(notes) or None


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	fields = (("revenue", _("Cash Revenue")), *((key, _(label)) for key, label in GAPS))
	return {
		"data": {
			"labels": [row["group"] or _("Unplaced") for row in rows],
			"datasets": [
				{"name": label, "values": [flt(row[key], 2) for row in rows]} for key, label in fields
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def get_summary(rows: list[dict]) -> list[dict]:
	if not rows:
		return []

	potential = sum(row["potential"] for row in rows)
	revenue = _total([row["revenue"] for row in rows])
	return [
		{
			"label": _("Yield"),
			"value": _percent(revenue, potential),
			"datatype": "Percent",
			"indicator": "Blue",
		},
		_inr(_("Potential Revenue (INR)"), potential),
		_inr(_("Cash Revenue (INR)"), revenue, "Green"),
		_biggest_gap(rows),
		_inr(_("Cost of Servers That Pay Nothing (INR)"), sum(row["unpaid_cost"] for row in rows), "Orange"),
	]


def _biggest_gap(rows: list[dict]) -> dict:
	gaps = {label: _total([row[key] for row in rows]) for key, label in GAPS}
	biggest = max((label for label in gaps if gaps[label] is not None), key=gaps.get)
	return _inr(_("Biggest Gap: {0} (INR)").format(_(biggest)), gaps[biggest], "Red")


def _inr(label: str, value: float | None, indicator: str | None = None) -> dict:
	return {"label": label, "value": value, "datatype": "Currency", "currency": "INR", "indicator": indicator}


def get_columns(group_by: str) -> list[dict]:
	if group_by == "Metal Server":
		group = [
			column(_("Metal Server"), "group", "Link", 150, options="Metal Server"),
			column(_("Region"), "region", "Link", 100, options="Region"),
		]
	else:
		group = [column(_("Region"), "group", "Link", 120, options="Region")]

	return [
		*group,
		column(_("Machines"), "machines", "Int", 80),
		column(_("Servers"), "servers", "Int", 80),
		column(_("Sellable vCPUs"), "sellable_vcpus", "Float", 110, precision=0),
		column(_("Sold vCPUs"), "sold_vcpus", "Float", 100, precision=0),
		column(_("vCPU Sold %"), "vcpu_sold_percent", "Percent", 100),
		column(_("Memory Sold %"), "memory_sold_percent", "Percent", 110),
		inr(_("Metal Cost (INR)"), "cost"),
		inr(_("Cost of Servers That Pay Nothing (INR)"), "unpaid_cost", 240),
		inr(_("Potential Revenue (INR)"), "potential", 160),
		inr(_("Unsold (INR)"), "unsold"),
		inr(_("Used Free (INR)"), "unpaid"),
		inr(_("Discount (INR)"), "discount"),
		inr(_("Cash Revenue (INR)"), "revenue", 140),
		column(_("Yield %"), "yield_percent", "Percent", 90),
		inr(_("Revenue per Sellable vCPU (INR)"), "revenue_per_sellable_vcpu", 200),
		inr(_("Revenue per Sold vCPU (INR)"), "revenue_per_sold_vcpu", 180),
	]


def _total(values: list) -> float | None:
	"""Sum of `values`, or None when one is unknown (USD revenue with no rate)."""
	return None if any(value is None for value in values) else sum(values)


def _ratio(part: float | None, whole: float) -> float | None:
	return None if part is None or not whole else flt(part / whole, 2)


def _percent(part: float | None, whole: float) -> float | None:
	return None if part is None or not whole else flt(100 * part / whole, 1)
