# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
import requests

from central.billing.india_gst import state_for_place_of_supply
from central.billing.ingester import connection
from central.billing.platform.jobs import each_isolated

PAGE = 100
MAX_PER_RUN = 1000
# An invoice whose filing cannot be read now.
SKIPPED = object()


def record_missing_gst_states() -> None:
	"""Daily: record the GST state of issued GST invoices that do not have one yet."""
	GstStateBackfill().run()


class GstStateBackfill:
	"""Records the state of invoices issued before the state was recorded at issue.

	A synced invoice takes the place of supply it was filed with; an unsynced one, the
	team's state at issue. One whose filing cannot be read now waits for the next run.
	"""

	def __init__(self):
		self.is_accounting_down = False
		self.seen = 0
		self.results = []

	def run(self) -> None:
		after = ""
		while self.seen < MAX_PER_RUN:
			names = _unrecorded_invoices(after, min(PAGE, MAX_PER_RUN - self.seen))
			if not names:
				break
			self.results += each_isolated("GST state backfill", "Invoice", names, self.record)
			self.seen += len(names)
			after = names[-1]
		if self.seen:
			skipped = sum(result is SKIPPED for result in self.results)
			frappe.logger("central").info(
				f"GST state backfill: {len(self.results) - skipped} recorded, {skipped} skipped, "
				f"{self.seen - len(self.results)} failed"
			)

	def record(self, invoice: str):
		"""Record one invoice's state and return it, or SKIPPED."""
		inv = frappe.db.get_value(
			"Invoice", invoice, ["name", "team", "erpnext_invoice", "creation"], as_dict=True
		)
		filed = self._filed_place_of_supply(inv.erpnext_invoice) if inv.erpnext_invoice else None
		if filed is SKIPPED:
			return SKIPPED
		state = state_for_place_of_supply(filed) if filed is not None else state_at_issue(inv)
		frappe.db.set_value(
			"Invoice", invoice, {"gst_state": state, "gst_state_recorded": 1}, update_modified=False
		)
		return state

	def _filed_place_of_supply(self, sales_invoice: str):
		"""The Sales Invoice's place of supply ("" if blank), None if it is gone, or SKIPPED."""
		if self.is_accounting_down or not connection.enabled():
			return SKIPPED
		try:
			record = connection.fetch("Sales Invoice", sales_invoice)
		except (requests.RequestException, connection.NoAccess):
			# One failed read stops the rest of this run reading; tomorrow's run tries again.
			self.is_accounting_down = True
			return SKIPPED
		return (record.place_of_supply or "") if record else None


def state_at_issue(invoice) -> str | None:
	"""The team's state at issue: the last one set by then, else the one before the
	first later change, else today's."""
	issued_at = _issued_at(invoice)
	changes = _state_changes(invoice.team)
	before = [new for at, _old, new in changes if at <= issued_at]
	if before:
		return before[-1] or None
	if changes:
		return changes[0][1] or None
	return frappe.db.get_value("Billing Profile", invoice.team, "state") or None


def _issued_at(invoice):
	"""When the invoice was issued; its creation if the audit trail does not say."""
	# A one-off reconstruction of the past, which is what the audit trail is for.
	event = frappe.qb.DocType("Billing Event")
	rows = (
		frappe.qb.from_(event)
		.select(event.occurred_at)
		.where(event.subject_doctype == "Invoice")
		.where(event.subject == invoice.name)
		.where(event.event_type.isin(["Invoice Issued", "Invoice Paid"]))
		.orderby(event.occurred_at)
		.limit(1)
		.run()
	)
	return frappe.utils.get_datetime(rows[0][0] if rows else invoice.creation)


def _state_changes(team: str) -> list[tuple]:
	"""Each change to the profile's state, oldest first, as (when, old, new)."""
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Billing Profile", "docname": team, "data": ["like", '%"state"%']},
		fields=["creation", "data"],
		order_by="creation asc",
	)
	return [
		(frappe.utils.get_datetime(v.creation), old, new)
		for v in versions
		for field, old, new in frappe.parse_json(v.data).get("changed") or []
		if field == "state"
	]


def _unrecorded_invoices(after: str, limit: int) -> list[str]:
	"""Issued INR invoices that charged GST and have no state recorded, by name after `after`."""
	invoice = frappe.qb.DocType("Invoice")
	return (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(invoice.name > after)
		.where(invoice.due_date.isnotnull())
		.where(invoice.currency == "INR")
		.where(invoice.output_tax_type == "GST")
		.where(invoice.output_tax_amount > 0)
		.where(invoice.gst_state_recorded == 0)
		.orderby(invoice.name)
		.limit(limit)
		.run(pluck=True)
	)
