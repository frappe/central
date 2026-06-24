# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.billing.catalog import configurator

_RUNG_FIELDS = ("plan_name", "label", "vcpu", "memory_gb", "disk_gb", "transfer_gb", "multiplier")


class PlanConfigurator(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from central.billing.doctype.plan_configurator_plan.plan_configurator_plan import PlanConfiguratorPlan
		from central.billing.doctype.plan_configurator_rate.plan_configurator_rate import PlanConfiguratorRate
		from central.billing.doctype.plan_configurator_simple_plan.plan_configurator_simple_plan import PlanConfiguratorSimplePlan
		from frappe.types import DF

		base_disk_gb: DF.Float
		base_rates: DF.Table[PlanConfiguratorRate]
		base_transfer_gb: DF.Float
		billing_cycle: DF.Literal["Monthly", "Annual"]
		builder: DF.ReadOnly | None
		category: DF.Link
		ceiling_vcpu: DF.Float
		is_active: DF.Check
		memory_ratio: DF.Literal["1:2", "1:4", "1:6", "1:8"]
		plan_name_prefix: DF.Data
		rungs: DF.Table[PlanConfiguratorPlan]
		simple_plans: DF.Table[PlanConfiguratorSimplePlan]
		start_vcpu: DF.Float
		sub_category: DF.Link | None
		template_name: DF.Data
		transfer_step_gb: DF.Float
	# end: auto-generated types

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
		return configurator.ratio_for(self.sub_category, self.memory_ratio)

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

	def _builder(self) -> str:
		"""The authoring builder for this configurator's family (ADR 0007)."""
		return frappe.db.get_value("Plan Category", self.category, "configurator_builder") or "VM Rungs"

	def _resolved_sub_category(self) -> str | None:
		"""The picked Sub-Category, or None. A custom one is minted inline via the
		Link's quick-create, so it's already a real Plan Sub-Category by the time we read it."""
		return self.sub_category or None

	@frappe.whitelist()
	def enqueue_generation(
		self,
		cluster: str | None = None,
		currencies: str | list | None = None,
		plans: str | list | None = None,
	) -> dict:
		"""Queue the (background) generation for a chosen cluster, currencies, and
		subset of plans. This picks where/what to ship; the specs are edited above."""
		if self._builder() == "Simple":
			if not self.simple_plans:
				frappe.throw("Add at least one plan row, then generate.")
		elif not self.rungs:
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
		"""Create the selected plans and price them at `cluster` in the selected
		base-rate currencies. Dispatches to the family's builder (ADR 0007). Synchronous
		core (the background job calls this). Idempotent on the Plans — an already-generated
		row is skipped, only its rates for the given cluster are added/updated."""
		if isinstance(plans, str):
			plans = frappe.parse_json(plans)
		if isinstance(currencies, str):
			currencies = frappe.parse_json(currencies)
		selected = set(plans) if plans else None
		if self._builder() == "Simple":
			return self._generate_simple(selected, cluster, currencies)
		return self._generate_vm_rungs(selected, cluster, currencies)

	def _generate_vm_rungs(self, selected, cluster, currencies) -> dict:
		rungs = [r for r in self.rungs if selected is None or r.plan_name in selected]
		if not rungs:
			frappe.throw("No rungs selected to generate.")
		result = configurator.generate_plans(
			rungs=rungs,
			billing_cycle=self.billing_cycle,
			is_active=cint(self.is_active),
			sub_category=self._resolved_sub_category(),
			category=self.category,
		)
		# generate_plans wrote each rung's minted hash onto row.plan in place; persist it.
		self.save(ignore_permissions=True)
		multipliers = [{"plan": r.plan, "multiplier": r.multiplier} for r in rungs]
		return {**result, **self._price(multipliers, cluster, currencies)}

	def _generate_simple(self, selected, cluster, currencies) -> dict:
		rows = [r for r in self.simple_plans if selected is None or r.title in selected]
		if not rows:
			frappe.throw("No plans selected to generate.")
		sub_category = self._resolved_sub_category()
		created, skipped = [], []
		for row in rows:
			if row.plan and frappe.db.exists("Plan", row.plan):
				skipped.append(row.plan)
				continue
			row.plan = configurator.create_simple_plan(
				self.category,
				row.title,
				row.resource_type,
				row.quantity,
				row.unit,
				sub_category=sub_category,
				billing_cycle=self.billing_cycle,
				is_active=cint(self.is_active),
			)
			created.append(row.plan)
		# create_simple_plan minted each row.plan in place; persist it. Runs in the
		# background generation job (run_generation) with no interactive user to
		# permission-check, hence ignore_permissions.
		self.save(ignore_permissions=True)
		multipliers = [{"plan": r.plan, "multiplier": flt(r.multiplier) or 1} for r in rows]
		return {"created": created, "skipped": skipped, **self._price(multipliers, cluster, currencies)}

	def _price(self, multipliers, cluster, currencies) -> dict:
		pricing = [
			configurator.apply_pricing(multipliers, br["currency"], br["base_rate"], cluster=cluster)
			for br in self._base_rates(set(currencies) if currencies else None)
		]
		return {"pricing": pricing, "cluster": cluster or None}


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
