# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.billing.catalog import configurator

_RUNG_FIELDS = ("plan_name", "label", "vcpu", "memory_gb", "disk_gb", "transfer_gb", "multiplier")


class PlanConfigurator(Document):
	def _ratio(self) -> str:
		return configurator.ratio_for(self.plan_class, self.memory_ratio)

	def _formula_rungs(self) -> list[dict]:
		return configurator.build_ladder(
			self.start_vcpu,
			self.ceiling_vcpu,
			self._ratio(),
			base_disk_gb=self.base_disk_gb,
			base_transfer_gb=self.base_transfer_gb,
			transfer_step_gb=self.transfer_step_gb,
			name_prefix=self.plan_name_prefix,
		)

	def _rung_rows(self) -> list[dict]:
		"""The current rungs as plain dicts — the edited table if populated, else the
		formula proposal (so Preview works before Populate)."""
		if self.rungs:
			return [{f: r.get(f) for f in _RUNG_FIELDS} for r in self.rungs]
		return self._formula_rungs()

	def _base_rates(self, currencies: set | None = None) -> list[dict]:
		rows = [
			{"currency": r.currency, "base_rate": flt(r.base_rate)}
			for r in self.base_rates
			if currencies is None or r.currency in currencies
		]
		if not rows:
			frappe.throw("Add at least one base rate (currency + price).")
		return rows

	@frappe.whitelist()
	def populate_rungs(self) -> dict:
		"""Fill the editable rungs table from the formula (overwrites the table)."""
		self.set("rungs", [])
		for r in self._formula_rungs():
			self.append("rungs", {f: r[f] for f in _RUNG_FIELDS})
		self.save(ignore_permissions=True)
		return {"count": len(self.rungs)}

	@frappe.whitelist()
	def preview(self) -> dict:
		"""The current rungs with a price per currency. Currency-aware, no writes."""
		rates = self._base_rates()
		rungs = [
			{
				**{f: r[f] for f in _RUNG_FIELDS},
				"rates": [
					{"currency": br["currency"], "rate": flt(br["base_rate"] * flt(r["multiplier"]), 2)}
					for br in rates
				],
			}
			for r in self._rung_rows()
		]
		return {"rungs": rungs, "currencies": [br["currency"] for br in rates]}

	@frappe.whitelist()
	def generate(self) -> dict:
		"""Create a bundle per (edited) rung and price it in every base-rate currency
		for the default cluster. Idempotent on the Plans."""
		if not self.rungs:
			frappe.throw("Populate the rungs first, then edit and generate.")
		result = configurator.generate_plans(
			self.rungs, billing_cycle=self.billing_cycle, is_active=cint(self.is_active)
		)
		for row in self.rungs:
			if frappe.db.exists("Plan", row.plan_name):
				row.plan = row.plan_name
		self.save(ignore_permissions=True)

		multipliers = [{"plan": r.plan_name, "multiplier": r.multiplier} for r in self.rungs]
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
	) -> list:
		"""Price a cluster over all generated rungs (or a subset), in all the
		template's base-rate currencies (or a subset). A plan is sellable on the
		cluster only where it has a rate (or a global one) — so subsets give
		selective availability."""
		if isinstance(plans, str):
			plans = frappe.parse_json(plans)
		if isinstance(currencies, str):
			currencies = frappe.parse_json(currencies)
		selected = set(plans) if plans else None

		multipliers = [
			{"plan": r.plan_name, "multiplier": r.multiplier}
			for r in self.rungs
			if selected is None or r.plan_name in selected
		]
		if not multipliers:
			frappe.throw("No generated plans selected to price.")

		return [
			configurator.apply_pricing(multipliers, br["currency"], br["base_rate"], cluster=cluster)
			for br in self._base_rates(set(currencies) if currencies else None)
		]
