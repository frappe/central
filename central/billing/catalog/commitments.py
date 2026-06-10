# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Commitment discount at invoice generation (issue #30).

A team-level Commitment is a fixed-bundle spend floor held for a term. While the
period's fixed-bundle spend meets the floor, the invoice's bundle spend is
discounted by `discount_pct`. The floor and the discount are measured on
fixed-bundle lines only (`resource_type == "bundle"`) — metered usage and
one-off add-ons are variable and bill at list. The discount reduces the taxable
base (see billing.py); it does not touch the line items or `subtotal`.

Breach detection + clawback is issue #31.
"""

import frappe

BUNDLE = "bundle"


def active_commitment(team: str, on_date=None) -> dict | None:
	"""The team's Active commitment whose term covers `on_date` (default today).

	Returns the commitment fields, or None when the team has no active commitment
	in force for that date.
	"""
	on_date = frappe.utils.getdate(on_date) if on_date else frappe.utils.getdate()
	row = frappe.db.get_value(
		"Commitment",
		{"team": team, "status": "Active"},
		["name", "floor", "discount_pct", "term_months", "started_at"],
		as_dict=True,
	)
	if not row:
		return None
	if row.started_at:
		start = frappe.utils.getdate(row.started_at)
		end = frappe.utils.add_months(start, int(row.term_months or 0))
		if not (start <= on_date < end):
			return None
	return row


def fixed_bundle_spend(lines: list[dict]) -> float:
	"""Sum of the fixed-bundle line amounts (the floor/discount base)."""
	return frappe.utils.flt(
		sum(line["amount"] for line in lines if line.get("resource_type") == BUNDLE), 2
	)


def discount_enjoyed(team: str, since) -> float:
	"""Total commitment discount already applied to the team's invoices since a
	date — the amount a breach must repay (issue #31).
	"""
	rows = frappe.get_all(
		"Invoice",
		filters={"team": team, "period_start": [">=", since], "status": ["!=", "Cancelled"]},
		pluck="commitment_discount",
	)
	return frappe.utils.flt(sum(frappe.utils.flt(r) for r in rows), 2)


def resolve_commitment(team: str, lines: list[dict], on_date=None) -> dict:
	"""Discount + clawback for this period under the team's active commitment.

	- floor met  → discount = `bundle_spend × discount_pct/100`, no clawback.
	- floor missed (breach, within term) → no discount; clawback repays the
	  discount enjoyed on consumed months; the commitment name is returned so the
	  caller can mark it Breached.
	- no active commitment → both zero.
	"""
	result = {"discount": 0.0, "clawback": 0.0, "breach": None}
	commitment = active_commitment(team, on_date)
	if not commitment:
		return result

	spend = fixed_bundle_spend(lines)
	if spend >= frappe.utils.flt(commitment.floor):
		result["discount"] = frappe.utils.flt(
			spend * frappe.utils.flt(commitment.discount_pct) / 100.0, 2
		)
		return result

	# Breach: dropped below the floor before term-end.
	result["clawback"] = discount_enjoyed(team, commitment.started_at)
	result["breach"] = commitment.name
	return result


def mark_breached(commitment: dict) -> None:
	"""Flip a breached commitment to Breached so later periods get no discount.

	No-op when the period did not breach. Idempotent — invoice generation is
	idempotent per (team, period), so this never double-applies.
	"""
	if commitment.get("breach"):
		frappe.db.set_value("Commitment", commitment["breach"], "status", "Breached")
