# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def apply_report(existing, mode: str, qty: float, seq: int, refuse_lower: bool) -> None:
	"""Apply a report to a locked rollup: Incremental adds a new batch, Authoritative replaces the total."""
	if mode == "Incremental":
		if seq <= frappe.utils.cint(existing.sequence):
			return  # A duplicate or out-of-order batch is already counted.
		frappe.db.set_value(
			"Usage Rollup",
			existing.name,
			{"quantity": frappe.utils.flt(existing.quantity) + qty, "sequence": seq},
		)
		return
	if refuse_lower and qty < frappe.utils.flt(existing.quantity):
		frappe.throw(
			_("A usage total for this period can only increase ({0} is recorded).").format(existing.quantity),
			frappe.ValidationError,
		)
	frappe.db.set_value("Usage Rollup", existing.name, "quantity", qty)


def rerate(existing, terms) -> None:
	"""Keep a converted rollup at the month's latest rate until its rate date is set."""
	if not (terms and terms.get("is_converted")) or existing.rate_date:
		return
	# The rate and its date are written together, so a rollup with a rate date is never re-rated.
	frappe.db.set_value(
		"Usage Rollup", existing.name, {"locked_rate": terms["rate"], "rate_date": terms.get("rate_date")}
	)


def recount_allowance(existing, meter: dict) -> None:
	"""Keep the bundle a recount counted from the month's days, which change until it is billed."""
	if "counted_allowance" in meter:
		frappe.db.set_value("Usage Rollup", existing.name, "locked_allowance", meter["counted_allowance"])
