# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate

from central.billing import settings
from central.billing.report._inventory import cost_per_vcpu, region_capacity

VM_SERVICE = "VM Plans"


def billing_month(filters: dict) -> tuple:
	"""The month a report reads: `filters.month`, else the last closed month."""
	month = getdate(filters.get("month")) if filters.get("month") else add_months(getdate(), -1)
	return get_first_day(month), get_last_day(month)


def to_inr(amount: float, currency: str | None) -> float | None:
	"""`amount` in INR, or None for USD when Billing Settings gives no report rate."""
	if not amount or currency in (None, "INR"):
		return flt(amount)
	rate = settings.reporting_usd_to_inr() if currency == "USD" else 0
	return flt(amount) * rate if rate else None


class BilledMonth:
	"""Every invoice line billed for one month, with its revenue in INR and what it cost us.

	Revenue is the pre-tax line amount; a waived invoice (our own team) earns nothing. Cost is
	the server's vCPU share of its region's bare metal for a VM bundle, or the quantity times
	the Resource Type's cost per unit for anything metered."""

	def __init__(self, filters: dict):
		self.start, self.end = billing_month(filters)
		self.filters = filters
		self.unit_costs = dict(
			frappe.get_all("Resource Type", fields=["name", "cost_per_unit_inr"], as_list=True)
		)
		self.capacity = region_capacity()
		self.lines = self._load()

	def _load(self) -> list:
		line = frappe.qb.DocType("Invoice Line Item")
		invoice = frappe.qb.DocType("Invoice")
		plan = frappe.qb.DocType("Plan")
		server = frappe.qb.DocType("Virtual Machine")
		query = (
			frappe.qb.from_(line)
			.join(invoice)
			.on(invoice.name == line.parent)
			.left_join(plan)
			.on(plan.name == line.plan)
			.left_join(server)
			.on(server.name == line.subscription_resource)
			.select(
				invoice.team,
				invoice.status,
				invoice.currency,
				line.plan,
				plan.category,
				line.resource_type,
				line.unit,
				line.quantity,
				line.amount,
				line.days,
				line.hours,
				line.subscription_resource.as_("server"),
				server.region,
				server.vcpus,
			)
			.where(line.parenttype == "Invoice")
			.where(invoice.invoice_type == "Billable")
			.where(invoice.status != "Cancelled")
			.where(invoice.period_start == self.start)
		)
		if self.filters.get("team"):
			query = query.where(invoice.team == self.filters["team"])
		rows = query.run(as_dict=True)
		days_in_month = (self.end - self.start).days + 1
		for row in rows:
			row.service = row.category or (VM_SERVICE if row.resource_type == "bundle" else row.resource_type)
			row.revenue_inr = 0.0 if row.status == "Waived" else to_inr(row.amount, row.currency)
			row.cost_inr = self._cost(row, days_in_month)
		return rows

	def _cost(self, row, days_in_month: int) -> float:
		if row.resource_type == "bundle":
			share = (flt(row.days) + flt(row.hours) / 24) / days_in_month
			return flt(row.vcpus) * cost_per_vcpu(self.capacity.get(row.region)) * share
		return flt(row.quantity) * flt(self.unit_costs.get(row.resource_type))
