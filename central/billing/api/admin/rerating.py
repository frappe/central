# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Operator endpoints for re-issuing a period after a price was found to be wrong."""

import frappe

from central.billing.authz import require_operator
from central.billing.revenue import metering, rerating


@frappe.whitelist()
def preview_rerating(resource_type: str, period_start: str, period_end: str) -> dict:
	"""What re-issuing this period would change. Changes nothing."""
	require_operator()
	return rerating.preview(resource_type, period_start, period_end)


@frappe.whitelist(methods=["POST"])
def apply_rerating(resource_type: str, period_start: str, period_end: str, reason: str) -> str:
	"""Re-issue the affected invoices and return the audit record's name."""
	require_operator()
	if not reason:
		frappe.throw("A re-rating needs a reason — it is the audit record.", frappe.ValidationError)
	return rerating.apply(resource_type, period_start, period_end, reason)


@frappe.whitelist(methods=["POST"])
def correct_rollup_terms(rollup: str, rate=None, allowance=None, reason: str | None = None) -> str:
	"""Re-price one usage rollup by writing a new version of it."""
	require_operator()
	return metering.override_terms(rollup, rate=rate, allowance=allowance, reason=reason)
