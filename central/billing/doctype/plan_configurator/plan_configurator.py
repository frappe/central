# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.billing.catalog import configurator


class PlanConfigurator(Document):
	def _ladder(self) -> list[dict]:
		return configurator.build_ladder(
			self.start_vcpu,
			self.ceiling_vcpu,
			self.memory_ratio,
			base_disk_gb=self.base_disk_gb,
			name_prefix=self.plan_name_prefix,
		)

	@frappe.whitelist()
	def preview(self) -> list[dict]:
		"""The rungs this template would generate — sizes + rates, no writes."""
		base = flt(self.base_rate)
		return [
			{
				"name": r["name"],
				"label": r["label"],
				"vcpu": r["vcpu"],
				"memory_gb": r["memory_gb"],
				"disk_gb": r["disk_gb"],
				"multiplier": r["multiplier"],
				"rate": flt(base * r["multiplier"], 2),
			}
			for r in self._ladder()
		]

	@frappe.whitelist()
	def generate(self) -> dict:
		"""Create the bundles + composition, record them on the template, and price
		them for the default currency + cluster. Idempotent on the Plans."""
		rungs = self._ladder()
		result = configurator.generate_plans(
			rungs, billing_cycle=self.billing_cycle, is_active=cint(self.is_active)
		)

		self.set("plans", [])
		for r in rungs:
			self.append("plans", {
				"plan": r["name"], "label": r["label"],
				"vcpu": r["vcpu"], "memory_gb": r["memory_gb"], "multiplier": r["multiplier"],
			})
		self.save(ignore_permissions=True)

		pricing = configurator.apply_pricing(
			[{"plan": r["name"], "multiplier": r["multiplier"]} for r in rungs],
			self.currency, self.base_rate, cluster=self.default_cluster,
		)
		return {**result, "pricing": pricing}

	@frappe.whitelist()
	def apply_pricing_to_cluster(
		self,
		cluster: str | None = None,
		currency: str | None = None,
		base_rate: float | None = None,
		plans: str | list | None = None,
	) -> dict:
		"""Price a cluster over all generated plans, or a selected subset.

		`plans`: list of Plan names to include (default all). `currency` / `base_rate`
		default to the template's. A plan is sellable on the cluster only where it
		has a rate (or a global one) — so a subset gives selective availability.
		"""
		if isinstance(plans, str):
			plans = frappe.parse_json(plans)
		selected = set(plans) if plans else None

		rows = [
			{"plan": p.plan, "multiplier": p.multiplier}
			for p in self.plans
			if selected is None or p.plan in selected
		]
		if not rows:
			frappe.throw("No generated plans selected to price.")

		return configurator.apply_pricing(
			rows,
			currency or self.currency,
			flt(base_rate) if base_rate else self.base_rate,
			cluster=cluster,
		)
