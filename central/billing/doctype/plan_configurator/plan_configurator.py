# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.billing.catalog import configurator


class PlanConfigurator(Document):
	def _ratio(self) -> str:
		return configurator.ratio_for(self.plan_class, self.memory_ratio)

	def _ladder(self) -> list[dict]:
		return configurator.build_ladder(
			self.start_vcpu,
			self.ceiling_vcpu,
			self._ratio(),
			base_disk_gb=self.base_disk_gb,
			name_prefix=self.plan_name_prefix,
		)

	def _base_rates(self, currencies: set | None = None) -> list[dict]:
		"""The (currency, base_rate) rows, optionally filtered to a currency set."""
		rows = [
			{"currency": r.currency, "base_rate": flt(r.base_rate)}
			for r in self.base_rates
			if currencies is None or r.currency in currencies
		]
		if not rows:
			frappe.throw("Add at least one base rate (currency + price).")
		return rows

	@frappe.whitelist()
	def preview(self) -> dict:
		"""The rungs this template would generate — each with a rate per currency.
		Currency-aware, no writes."""
		rates = self._base_rates()
		rungs = [
			{
				"name": r["name"],
				"label": r["label"],
				"vcpu": r["vcpu"],
				"memory_gb": r["memory_gb"],
				"disk_gb": r["disk_gb"],
				"multiplier": r["multiplier"],
				"rates": [
					{"currency": br["currency"], "rate": flt(br["base_rate"] * r["multiplier"], 2)}
					for br in rates
				],
			}
			for r in self._ladder()
		]
		return {"rungs": rungs, "currencies": [br["currency"] for br in rates]}

	@frappe.whitelist()
	def generate(self) -> dict:
		"""Create the bundles + composition, record them on the template, and price
		them in every base-rate currency for the default cluster. Idempotent on Plans."""
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

		multipliers = [{"plan": r["name"], "multiplier": r["multiplier"]} for r in rungs]
		pricing = [
			configurator.apply_pricing(
				multipliers, br["currency"], br["base_rate"], cluster=self.default_cluster
			)
			for br in self._base_rates()
		]
		return {**result, "pricing": pricing}

	@frappe.whitelist()
	def apply_pricing_to_cluster(
		self,
		cluster: str | None = None,
		currencies: str | list | None = None,
		plans: str | list | None = None,
	) -> dict:
		"""Price a cluster over all generated plans (or a subset), in all the
		template's base-rate currencies (or a subset).

		A plan is sellable on the cluster only where it has a rate (or a global one),
		so selecting subsets of plans/currencies gives selective availability.
		"""
		if isinstance(plans, str):
			plans = frappe.parse_json(plans)
		if isinstance(currencies, str):
			currencies = frappe.parse_json(currencies)
		selected = set(plans) if plans else None

		multipliers = [
			{"plan": p.plan, "multiplier": p.multiplier}
			for p in self.plans
			if selected is None or p.plan in selected
		]
		if not multipliers:
			frappe.throw("No generated plans selected to price.")

		return [
			configurator.apply_pricing(
				multipliers, br["currency"], br["base_rate"], cluster=cluster
			)
			for br in self._base_rates(set(currencies) if currencies else None)
		]
