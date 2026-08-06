# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Where a projected line's quantity came from, and therefore how much to trust it.

A projected invoice has two kinds of line and they must never be read as one number.
A fixed bundle charge projects into a month that has not started as a plain fact —
the rate is locked on the subscription's change row and the days are arithmetic. A
metered charge cannot: nobody has used the bandwidth yet, so any figure is inferred.

Reporting both under one total is how a bill that is half guesswork comes to read
like a bill. So every line carries its basis, and totals are split by it.
"""

MEASURED = "Measured"  # already a fact: a locked rate over elapsed days, a landed rollup
ESTIMATED = "Estimated"  # inferred from history, because the period has not happened
ASSUMED = "Assumed"  # a human asserted it in the scenario


def split_totals(lines: list[dict]) -> dict:
	"""Sum the lines by basis, so a total is never quoted without its provenance."""
	totals = {MEASURED: 0.0, ESTIMATED: 0.0, ASSUMED: 0.0}
	for line in lines:
		totals[line.get("basis", MEASURED)] += line.get("amount") or 0.0
	return {
		"measured": round(totals[MEASURED], 2),
		"estimated": round(totals[ESTIMATED], 2),
		"assumed": round(totals[ASSUMED], 2),
		# True when any part of this figure is inferred rather than observed. The UI
		# uses it to refuse to render a bare total.
		"has_estimates": bool(totals[ESTIMATED] or totals[ASSUMED]),
	}


def mark(lines: list[dict], basis: str) -> list[dict]:
	"""Stamp a basis onto lines that do not already carry one."""
	for line in lines:
		line.setdefault("basis", basis)
	return lines
