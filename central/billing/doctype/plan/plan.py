# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


class Plan(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.billing.doctype.plan_includes.plan_includes import PlanIncludes

		annual_discount_pct: DF.Float
		available_on_trial: DF.Check
		billing_cycle: DF.Literal["Monthly", "Annual"]
		category: DF.Link
		includes: DF.Table[PlanIncludes]
		is_active: DF.Check
		sub_category: DF.Link | None
		title: DF.Data
	# end: auto-generated types

	def validate(self):
		self._validate_has_includes()
		self._validate_sub_category()
		self._validate_includes_against_category()
		self._validate_unique_metered_resource()

	def _validate_has_includes(self):
		"""A Plan must declare what it bills: at least one `Plan Includes` row (#85).
		An empty composition is a price with no subject — `is_metered_single_resource`
		keys off the single include, and a bundle needs its composition. The field is
		also `reqd`; this surfaces the invariant with a clear message server-side."""
		if not self.includes:
			frappe.throw(_("A Plan must include at least one resource — it needs to declare what it bills."))

	def is_metered_single_resource(self) -> bool:
		"""True when this Plan is a metering target: a single-resource plan under a
		`Metered` Plan Category (ADR 0008). This is what `metering.py` resolves by
		resource type."""
		if len(self.includes) != 1 or not self.category:
			return False
		return frappe.db.get_value("Plan Category", self.category, "billing_type") == "Metered"

	def _validate_unique_metered_resource(self):
		"""At most one *active* metered single-resource Plan may exist per resource type,
		so metering's resolution is unambiguous (ADR 0008). The old global Add-on lookup
		silently picked one row; this surfaces the collision at save time instead."""
		if not self.is_active or not self.is_metered_single_resource():
			return
		resource_type = self.includes[0].resource_type
		metered_cats = frappe.get_all("Plan Category", filters={"billing_type": "Metered"}, pluck="name")
		others = frappe.get_all(
			"Plan",
			filters={"category": ["in", metered_cats], "is_active": 1, "name": ["!=", self.name]},
			pluck="name",
		)
		if not others:
			return

		# One batched read of every other plan's composition, grouped by plan, instead of
		# a query per plan.
		includes_by_plan: dict[str, list[str]] = {}
		for inc in frappe.get_all(
			"Plan Includes", filters={"parent": ["in", others]}, fields=["parent", "resource_type"]
		):
			includes_by_plan.setdefault(inc.parent, []).append(inc.resource_type)

		for other in others:
			includes = includes_by_plan.get(other, [])
			if len(includes) == 1 and includes[0] == resource_type:
				frappe.throw(
					_(
						"An active metered plan ({0}) already prices resource type {1}. "
						"At most one active metered plan may cover a resource type."
					).format(other, resource_type)
				)

	def _validate_sub_category(self):
		"""A chosen sub-category must belong to this plan's category (ADR 0007)."""
		if not self.sub_category:
			return
		owner = frappe.db.get_value("Plan Sub-Category", self.sub_category, "category")
		if owner != self.category:
			frappe.throw(
				_("Sub-Category {0} belongs to {1}, not {2}.").format(self.sub_category, owner, self.category)
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
				_("Resource type(s) {0} are not allowed in category {1} (allowed: {2}).").format(
					", ".join(sorted(offenders)), self.category, ", ".join(sorted(allowed))
				)
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
				{"cluster": r.cluster or None, "currency": r.currency, "rate": r.rate} for r in rate_rows
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
