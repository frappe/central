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
from frappe import _

from central.billing import settings
from central.billing.catalog import pricing
from central.billing.projection import cassette, engine, repricing

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
			_("This scenario has no team. Cohort scenarios are projected from the "
			"Billing Projection report."),
			frappe.ValidationError,
		)

	overrides = doc.overrides()
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(doc.period_start or today)
	months = max(1, frappe.utils.cint(doc.months) or 1)

	rates = doc.rate_overrides_applied()
	events = doc.injected_events()
	with settings.overridden(**overrides), pricing.overridden_rates(rates):
		if months > 1:
			out = engine.project_months(
				doc.team, period_start, months=months, today=today,
				mode=doc.outcome_mode, assume=doc.assume, events=events,
			)
		else:
			out = engine.project(
				doc.team, period_start, frappe.utils.get_last_day(period_start), today=today,
				mode=doc.outcome_mode, assume=doc.assume, events=events,
			)

	# What a price change actually reaches — the part everyone gets wrong.
	if rates:
		out["repricing"] = repricing.split(
			_all_lines(out), out.get("currency"), doc.effective_from()
		)

	# Say what was pretended. A projection under an altered ladder that does not
	# announce it is a number waiting to be quoted as fact.
	out["scenario"] = {
		"name": doc.name,
		"scenario_name": doc.scenario_name,
		"overrides": overrides,
		"rate_overrides": rates,
		"events": events,
		"outcome_mode": doc.outcome_mode,
		"months": months,
	}
	return out


def _all_lines(out) -> list:
	"""Every projected line, whether the projection was one month or several."""
	if out.get("months"):
		return [
			line
			for month in out["months"]
			for line in ((month.get("invoice") or {}).get("lines") or [])
		]
	return (out.get("invoice") or {}).get("lines") or []


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

	rates = doc.rate_overrides_applied()
	events = doc.injected_events()
	# Events count as a difference too. Leaving them out compared a scenario against
	# itself and reported "no change" for the one thing that had changed.
	varies = bool(overrides or rates or events)

	live = project(_bare(doc), today)
	altered = project(doc, today) if varies else live

	result = {
		"overrides": overrides,
		"rate_overrides": rates,
		"events": events,
		"live": live,
		"altered": altered,
		"changed": varies,
	}
	if rates:
		# Say what the number means, because the number alone is the thing that gets
		# misread: a catalog change does not reach a locked rate.
		result["repricing"] = repricing.with_delta(
			altered["repricing"], _total(live), _total(altered)
		)
		result["explanation"] = repricing.explain(
			_total(live), _total(altered), altered["repricing"]
		)
	return result


def _total(out) -> float:
	if out.get("months"):
		return frappe.utils.flt(
			sum(frappe.utils.flt((m.get("invoice") or {}).get("total")) for m in out["months"]), 2
		)
	return frappe.utils.flt((out.get("invoice") or {}).get("total"), 2)


def _bare(doc):
	"""The same scenario with its overrides dropped — the live-configuration control."""
	clone = frappe.copy_doc(doc)
	from central.billing.doctype.billing_scenario.billing_scenario import OVERRIDE_FIELDS

	for field in OVERRIDE_FIELDS:
		clone.set(field, None)
	clone.set("rate_overrides", [])
	clone.set("events", [])
	return clone


def _resolve(scenario):
	return scenario if hasattr(scenario, "overrides") else frappe.get_doc("Billing Scenario", scenario)


def check_drift(scenario, today=None) -> dict:
	"""Has this scenario's answer changed since it was last saved?

	The regression harness, in the smallest form that is actually useful. A saved
	scenario already holds its inputs and its last answer, so re-projecting it and
	diffing gives exactly what a deploy check needs: same question, same team, different
	code.

	It is not immune to data drift — the team may genuinely have changed — so the
	report says what moved and where, and leaves the judgement to a human. Freezing the
	inputs too is the cassette's job, and this is where a recording would be replayed
	from once there is one.
	"""
	doc = _resolve(scenario)
	if not doc.result:
		frappe.throw(
			_("This scenario has no saved answer to compare against. Project and save it "
			"first."),
			frappe.ValidationError,
		)

	before = frappe.parse_json(doc.result)
	after = project(doc, today)
	report = cassette.report(before, after)
	return {
		"scenario": doc.name,
		"projected_at": str(doc.projected_at) if doc.projected_at else None,
		**report,
	}


def check_all(today=None) -> list[dict]:
	"""Every saved scenario, re-projected and diffed. What runs after a deploy."""
	out = []
	for name in frappe.get_all(
		"Billing Scenario", filters={"result": ["is", "set"]}, pluck="name"
	):
		try:
			out.append(check_drift(name, today))
		except Exception:
			frappe.log_error(
				title="Billing Scenario Drift Check Failed",
				message=frappe.get_traceback(),
				reference_doctype="Billing Scenario",
				reference_name=name,
			)
	return out
