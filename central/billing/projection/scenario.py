# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Projecting under a scenario, and saving one.

A **scenario** is the input bundle: which configuration to read, over what period, and
how to treat payment outcomes nobody can know. Varying it while holding the team fixed
is how "what would this change do?" gets asked.

The write boundary is the load-bearing part. The engine runs read-only — that is a
database guarantee, not a convention — so it returns plain data and *then*, in an
ordinary transaction, the result is stored on the scenario. Nothing else is written.
That restriction is the only thing standing between "saves a scenario" and "saves an
invoice", so it carries its own test.
"""

import frappe

from central.billing import settings
from central.billing.projection import engine

# The only DocType this module may write. Asserted, because the whole safety argument
# for running projections against production rests on it staying true.
WRITABLE = ("Billing Scenario",)


def project(scenario, today=None) -> dict:
	"""Project a scenario's subject under its overrides. Reads only.

	The overrides wrap the engine call rather than being passed into it: policy is read
	several layers down — dunning, invoicing, credits — and threading a settings bundle
	through all of them would push the simulator's concerns into code that has no
	business knowing it exists.
	"""
	doc = _resolve(scenario)
	if not doc.team:
		frappe.throw(
			"This scenario has no team. Cohort scenarios are projected from the "
			"Billing Projection report.",
			frappe.ValidationError,
		)

	overrides = doc.overrides()
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(doc.period_start or today)
	months = max(1, frappe.utils.cint(doc.months) or 1)

	with settings.overridden(**overrides):
		if months > 1:
			out = engine.project_months(
				doc.team, period_start, months=months, today=today,
				mode=doc.outcome_mode, assume=doc.assume,
			)
		else:
			out = engine.project(
				doc.team, period_start, frappe.utils.get_last_day(period_start), today=today,
				mode=doc.outcome_mode, assume=doc.assume,
			)

	# Say what was pretended. A projection under an altered ladder that does not
	# announce it is a number waiting to be quoted as fact.
	out["scenario"] = {
		"name": doc.name,
		"scenario_name": doc.scenario_name,
		"overrides": overrides,
		"outcome_mode": doc.outcome_mode,
		"months": months,
	}
	return out


def project_and_save(scenario, today=None) -> dict:
	"""Project, then record the result on the scenario — two transactions, in order.

	The projection happens read-only and finishes before anything is written. Storing
	the answer is an ordinary write, and it touches the scenario and nothing else.
	"""
	out = project(scenario, today)
	doc = _resolve(scenario)
	doc.db_set("result", frappe.as_json(out), commit=False)
	doc.db_set("projected_at", frappe.utils.now(), commit=False)
	frappe.db.commit()
	return out


def compare(scenario, today=None) -> dict:
	"""The same team, projected twice: as configured, and as the scenario pretends.

	Both halves come from one engine, so a difference between them is the override and
	nothing else — which is the only way the answer means anything.
	"""
	doc = _resolve(scenario)
	overrides = doc.overrides()

	live = project(_bare(doc), today)
	altered = project(doc, today) if overrides else live
	return {
		"overrides": overrides,
		"live": live,
		"altered": altered,
		"changed": bool(overrides),
	}


def _bare(doc):
	"""The same scenario with its overrides dropped — the live-configuration control."""
	clone = frappe.copy_doc(doc)
	from central.billing.doctype.billing_scenario.billing_scenario import OVERRIDE_FIELDS

	for field in OVERRIDE_FIELDS:
		clone.set(field, None)
	return clone


def _resolve(scenario):
	return scenario if hasattr(scenario, "overrides") else frappe.get_doc("Billing Scenario", scenario)
