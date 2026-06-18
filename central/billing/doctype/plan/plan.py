# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


class Plan(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from central.billing.doctype.plan_includes.plan_includes import PlanIncludes
		from frappe.types import DF

		annual_discount_pct: DF.Float
		billing_cycle: DF.Literal["Monthly", "Annual"]
		includes: DF.Table[PlanIncludes]
		is_active: DF.Check
		plan_class: DF.Literal["General", "CPU Optimised", "Memory Optimised", "Storage Optimised", "Custom"]
		title: DF.Data
	# end: auto-generated types

	def get_rate(self, currency: str, cluster: str | None = None):
		"""Resolved flat rate for (currency, cluster). The rate IS the price."""
		return resolve_rate(get_catalog_rates("Plan", self.name), currency, cluster)

	def as_pricing(self, currency: str | None = None, cluster: str | None = None) -> dict:
		"""Catalog snapshot: identity + composition + rates.

		With a currency, also resolves the single applicable rate. Consumed by
		get_plan_pricing and by the push to an Agent's Plan Cache.
		"""
		rate_rows = get_catalog_rates("Plan", self.name)
		data = {
			"plan": self.name,
			"title": self.title,
			"billing_cycle": self.billing_cycle,
			"is_active": self.is_active,
			"rates": [
				{"cluster": r.cluster or None, "currency": r.currency, "rate": r.rate}
				for r in rate_rows
			],
			"includes": [
				{
					"resource_type": i.resource_type,
					"quantity": i.quantity,
					"unit": i.unit,
				}
				for i in self.includes
			],
		}
		if currency:
			data["currency"] = currency
			data["cluster"] = cluster
			data["rate"] = self.get_rate(currency, cluster)
		return data
