# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a change would do to the whole book, not just to one team.

Per team, a diff answers "what does this do to *them*". Across a cohort it answers the
question an operator actually has before shipping a pricing or policy change: **how far
does this reach?**

> **The metric set below is provisional.** The issue this implements is marked HITL
> precisely because which numbers matter is a conversation with the accounts team, not a
> derivation — revenue delta is obvious, but "teams newly failing" versus "teams newly
> *at risk*", or whether a suspension moving counts the same as one appearing, are
> judgement calls. What is here is a defensible default chosen to be easy to argue with:
> every figure is counted from the two projections rather than modelled, so swapping the
> set is a change to this file and nothing else.

Two rules hold whatever the set becomes. Money never crosses currencies. And an
extrapolated figure says so wherever it appears, because a sampled blast radius quoted
as a measured one is the most expensive kind of wrong here.
"""

import frappe

# Counted from the pair of projections, never modelled. Each is one line to change.
METRICS = (
	"teams",
	"revenue_delta",
	"newly_short",
	"newly_suspending",
	"suspension_moved_earlier",
	"suspension_moved_later",
)


def compare_rows(live_rows: list[dict], altered_rows: list[dict]) -> dict:
	"""The aggregate difference between two cohort projections of the same teams.

	Both sides must come from the same engine over the same teams at the same instant,
	or the difference is not attributable to the change.
	"""
	live = {row["team"]: row for row in live_rows}
	altered = {row["team"]: row for row in altered_rows}
	shared = sorted(set(live) & set(altered))

	revenue: dict = {}
	newly_short, newly_suspending = [], []
	earlier, later = [], []

	for team in shared:
		before, after = live[team], altered[team]
		currency = after.get("currency") or before.get("currency")
		if currency:
			revenue.setdefault(currency, 0.0)
			revenue[currency] += frappe.utils.flt(after.get("projected_total")) - frappe.utils.flt(
				before.get("projected_total")
			)

		if frappe.utils.flt(after.get("shortfall")) > 0 >= frappe.utils.flt(before.get("shortfall")):
			newly_short.append(team)

		was, now = before.get("suspends_on"), after.get("suspends_on")
		if now and not was:
			newly_suspending.append(team)
		elif now and was and str(now) != str(was):
			(earlier if str(now) < str(was) else later).append(team)

	return {
		"teams": len(shared),
		# Per currency, always. There is no meaningful sum of rupees and dollars, and a
		# blast radius that produced one would be quoted anyway.
		"revenue_delta": {c: frappe.utils.flt(v, 2) for c, v in sorted(revenue.items())},
		"newly_short": newly_short,
		"newly_suspending": newly_suspending,
		"suspension_moved_earlier": earlier,
		"suspension_moved_later": later,
		"provisional_metrics": True,
	}


def summarise(comparison: dict, sampled: bool = False, sample_size: int = 0, population: int = 0) -> dict:
	"""Counts rather than lists, plus the labelling a sampled figure must carry."""
	out = {
		"teams": comparison["teams"],
		"revenue_delta": comparison["revenue_delta"],
		"newly_short": len(comparison["newly_short"]),
		"newly_suspending": len(comparison["newly_suspending"]),
		"suspension_moved_earlier": len(comparison["suspension_moved_earlier"]),
		"suspension_moved_later": len(comparison["suspension_moved_later"]),
		"provisional_metrics": True,
		"sampled": bool(sampled),
	}
	if sampled:
		out["sample_size"] = sample_size
		out["population"] = population
		# Extrapolate the money, never the counts: scaling "3 teams newly suspending" to
		# a population invents teams, and somebody will go looking for them.
		factor = (population / sample_size) if sample_size else 0
		out["revenue_delta_extrapolated"] = {
			c: frappe.utils.flt(v * factor, 2) for c, v in comparison["revenue_delta"].items()
		}
		out["note"] = (
			f"Extrapolated from {sample_size} of {population} teams. The money is scaled; "
			"the team counts are what was actually seen in the sample."
		)
	return out


def describe(summary: dict) -> str:
	"""One line an operator can take into a decision."""
	money = ", ".join(
		f"{currency} {amount:,.2f}"
		for currency, amount in (summary.get("revenue_delta") or {}).items()
		if amount
	)
	parts = [f"{summary['teams']} teams"]
	if money:
		parts.append(money)
	if summary["newly_suspending"]:
		parts.append(f"{summary['newly_suspending']} newly suspending")
	if summary["suspension_moved_earlier"]:
		parts.append(f"{summary['suspension_moved_earlier']} cut off sooner")
	if summary["newly_short"]:
		parts.append(f"{summary['newly_short']} newly short")
	if len(parts) == 1:
		return f"{summary['teams']} teams, and nothing measurable changes for any of them."
	return " · ".join(parts)
