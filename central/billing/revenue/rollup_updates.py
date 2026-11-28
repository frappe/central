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


def rerated(existing, terms) -> dict:
	"""A converted month's latest rate, until its rate date is set."""
	if not (terms and terms.get("is_converted")) or existing.rate_date:
		return {}
	# The rate and its date are written together, so a month with a rate date is never re-rated.
	return {"locked_rate": terms["rate"], "rate_date": terms.get("rate_date")}


def recounted_allowance(meter: dict, is_corrected: bool = False) -> dict:
	"""The bundle a recount counted from the month's days, which change until it is billed."""
	if "counted_allowance" in meter and not is_corrected:
		return {"locked_allowance": meter["counted_allowance"]}
	return {}


def live_rollup(name: str) -> str:
	"""Follow a rollup's supersede chain to the row that is actually billed."""
	seen = {name}
	while True:
		nxt = frappe.db.get_value("Usage Rollup", name, "superseded_by")
		if not nxt or nxt in seen:
			return name
		seen.add(nxt)
		name = nxt


def override_terms(rollup: str, rate=None, allowance=None, reason: str | None = None) -> str:
	"""Re-price one rollup a service reported by writing a new version of it, never by editing the old.

	Locked terms are what makes a metered charge auditable, so a correction adds a row
	and points the old one at it. The quantity carries over; only the terms move. A usage
	month is re-priced in place instead, with its old and new terms kept in a comment.
	"""
	name = live_rollup(rollup)
	old = frappe.get_doc("Usage Rollup", name)
	if rate is None and allowance is None:
		frappe.throw(_("Nothing to correct: give a rate, an allowance, or both."), frappe.ValidationError)

	new = frappe.copy_doc(old)
	new.locked_rate = old.locked_rate if rate is None else rate
	new.locked_allowance = old.locked_allowance if allowance is None else allowance
	new.superseded_by = None
	# The key says which versions moved the allowance, so a recount leaves those alone.
	mark = "v" if allowance is None else "a"
	new.idempotency_key = f"{old.idempotency_key}::{mark}{_version_of(old.idempotency_key) + 1}"
	new.insert(ignore_permissions=True)

	frappe.db.set_value("Usage Rollup", name, "superseded_by", new.name)
	old.add_comment("Info", f"Terms corrected -> {new.name}: {reason or 'no reason given'}")
	return new.name


def _version_of(idempotency_key: str) -> int:
	"""The version suffix on a rollup key, 0 for an original."""
	_head, sep, tail = idempotency_key.rpartition("::")
	return frappe.utils.cint(tail[1:]) if sep and is_version_mark(tail, "va") else 0


def is_allowance_corrected(idempotency_key: str) -> bool:
	"""Whether an operator corrected the allowance in this version of a rollup or an earlier one."""
	return any(is_version_mark(part, "a") for part in idempotency_key.split("::")[1:])


def is_version_mark(part: str, marks: str) -> bool:
	return part[:1] in marks and part[1:].isdigit()


def correct_terms(name: str, rate=None, allowance=None, reason: str | None = None) -> str:
	"""Re-price one usage month, or one rollup a service reported, and return the row that is billed."""
	if frappe.db.exists("Usage Month", name):
		return override_month_terms(name, rate=rate, allowance=allowance, reason=reason)
	return override_terms(name, rate=rate, allowance=allowance, reason=reason)


def override_month_terms(name: str, rate=None, allowance=None, reason: str | None = None) -> str:
	"""Re-price a usage month in place, and record its old and new terms on it."""
	if rate is None and allowance is None:
		frappe.throw(_("Nothing to correct: give a rate, an allowance, or both."), frappe.ValidationError)
	old = frappe.db.get_value("Usage Month", name, ["locked_rate", "locked_allowance"], as_dict=True)
	updates = {}
	if rate is not None:
		updates["locked_rate"] = frappe.utils.flt(rate)
	if allowance is not None:
		# A recount keeps an allowance an operator set.
		updates.update(locked_allowance=frappe.utils.flt(allowance), terms_corrected=1)
	frappe.db.set_value("Usage Month", name, updates, update_modified=False)
	new = frappe._dict(old, **updates)
	frappe.get_doc("Usage Month", name).add_comment(
		"Info",
		f"Terms corrected: rate {old.locked_rate} to {new.locked_rate}, allowance "
		f"{old.locked_allowance} to {new.locked_allowance}. Reason: {reason or 'none given'}",
	)
	return name
