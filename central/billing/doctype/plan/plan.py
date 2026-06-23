# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
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
		category: DF.Link
		includes: DF.Table[PlanIncludes]
		is_active: DF.Check
		sub_category: DF.Link | None
		title: DF.Data
	# end: auto-generated types

	def validate(self):
		self._validate_sub_category()
		self._validate_includes_against_category()

	def _validate_sub_category(self):
		"""A chosen sub-category must belong to this plan's category (ADR 0007)."""
		if not self.sub_category:
			return
		owner = frappe.db.get_value("Plan Sub-Category", self.sub_category, "category")
		if owner != self.category:
			frappe.throw(
				f"Sub-Category {self.sub_category!r} belongs to {owner!r}, not {self.category!r}."
			)

	def _validate_includes_against_category(self):
		"""Composition may only use the category's allowed resource types. A blank
		allow-list leaves the family unconstrained."""
		if not self.category:
			return
		allowed = set(
			frappe.get_all(
				"Plan Category Resource Type",
				filters={"parent": self.category},
				pluck="resource_type",
			)
		)
		if not allowed:
			return
		offenders = {i.resource_type for i in self.includes if i.resource_type not in allowed}
		if offenders:
			frappe.throw(
				f"Resource type(s) {', '.join(sorted(offenders))} are not allowed in category "
				f"{self.category!r} (allowed: {', '.join(sorted(allowed))})."
			)

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
