# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Run — one durable row per period, holding what the run achieved."""

import frappe
from frappe.model.document import Document

from central.billing.states import transition


class BillingRun(Document):
	pass


def snapshot(status: dict, to_state: str | None = None) -> str:
	"""Upsert the period's row from a freshly derived run status.

	The counters are re-read from the tables every time rather than accumulated, so a
	run that half happened still reports the truth.
	"""
	period_end = status["period_end"]
	if not frappe.db.exists("Billing Run", period_end):
		# Inserted before anything else so the row is named: a transition records the
		# document it moved, and an unsaved doc has no name to record.
		frappe.get_doc(
			{
				"doctype": "Billing Run",
				"period_end": period_end,
				"period_start": status["period_start"],
				"status": "Drafting",
				"started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

	doc = frappe.get_doc("Billing Run", period_end)
	doc.period_start = status["period_start"]
	doc.teams = status["teams"]
	doc.drafted = status["drafted"]
	doc.pending_draft = status["pending_draft"]
	doc.collected = status["collected"]
	doc.pending_collection = status["pending_collection"]
	doc.failures = status["failures"]
	doc.by_status = frappe.as_json(status["by_status"], indent=1)

	if to_state and to_state != doc.status:
		transition(doc, to_state, reason="billing run", actor=frappe.session.user)
	if doc.status == "Complete" and not doc.completed_at:
		doc.completed_at = frappe.utils.now_datetime()

	doc.save(ignore_permissions=True)
	return doc.name
