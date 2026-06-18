# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.billing.catalog import configurator

_RUNG_FIELDS = ("plan_name", "label", "vcpu", "memory_gb", "disk_gb", "transfer_gb", "multiplier")


class PlanConfigurator(Document):
	def before_validate(self):
		"""Fill identity/price for hand-added or edited rungs, so an inserted size
		(e.g. 1 vCPU 3 GB between the 2 GB and 4 GB rungs) is usable without the
		admin spelling out its name, label, and multiplier."""
		start = flt(self.start_vcpu) or 1
		for r in self.rungs:
			if not flt(r.multiplier) and flt(r.vcpu):
				r.multiplier = flt(r.vcpu) / start
			if flt(r.vcpu) and flt(r.memory_gb) and (not r.plan_name or not r.label):
				ident = configurator.rung_identity(r.vcpu, r.memory_gb, self.plan_name_prefix)
				r.plan_name = r.plan_name or ident["plan_name"]
				r.label = r.label or ident["label"]

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
	def enqueue_generation(
		self,
		cluster: str | None = None,
		currencies: str | list | None = None,
		plans: str | list | None = None,
	) -> dict:
		"""Queue the (background) generation for a chosen cluster, currencies, and
		subset of rungs. Editing of the rung specs happens in the Rungs table on the
		form; this picks where/what to ship."""
		if not self.rungs:
			frappe.throw("Populate the rungs first, then edit and generate.")
		frappe.enqueue(
			run_generation,
			queue="long",
			configurator=self.name,
			cluster=cluster,
			currencies=currencies,
			plans=plans,
			user=frappe.session.user,
		)
		return {"enqueued": True, "cluster": cluster or None}

	def generate_and_price(
		self,
		cluster: str | None = None,
		currencies: str | list | None = None,
		plans: str | list | None = None,
	) -> dict:
		"""Create a bundle per selected rung and price it at `cluster` in the selected
		base-rate currencies. Synchronous core (the background job calls this).

		Idempotent on the Plans (existing ones are skipped, only their rates for the
		given cluster are added/updated)."""
		if isinstance(plans, str):
			plans = frappe.parse_json(plans)
		if isinstance(currencies, str):
			currencies = frappe.parse_json(currencies)
		selected = set(plans) if plans else None

		rungs = [r for r in self.rungs if selected is None or r.plan_name in selected]
		if not rungs:
			frappe.throw("No rungs selected to generate.")

		result = configurator.generate_plans(
			rungs, billing_cycle=self.billing_cycle, is_active=cint(self.is_active)
		)
		for row in self.rungs:
			if frappe.db.exists("Plan", row.plan_name):
				row.plan = row.plan_name
		self.save(ignore_permissions=True)

		multipliers = [{"plan": r.plan_name, "multiplier": r.multiplier} for r in rungs]
		pricing = [
			configurator.apply_pricing(multipliers, br["currency"], br["base_rate"], cluster=cluster)
			for br in self._base_rates(set(currencies) if currencies else None)
		]
		return {**result, "pricing": pricing, "cluster": cluster or None}


def run_generation(configurator, cluster=None, currencies=None, plans=None, user=None):
	"""Background entrypoint: generate + price, then notify the user who queued it."""
	doc = frappe.get_doc("Plan Configurator", configurator)
	result = doc.generate_and_price(cluster=cluster, currencies=currencies, plans=plans)
	frappe.db.commit()
	if user:
		frappe.publish_realtime(
			"plan_configurator_done",
			message={"configurator": configurator, "cluster": cluster or "global", **result},
			user=user,
		)
	return result
