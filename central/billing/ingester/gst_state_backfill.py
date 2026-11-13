# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
import requests

from central.billing.india_gst import state_for_place_of_supply
from central.billing.ingester import connection
from central.billing.platform.jobs import each_isolated

PAGE = 100
MAX_PER_RUN = 1000
SKIPPED = object()
CURSOR_KEY = "gst_state_backfill:after"


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
		# Unsynced invoices are always recorded, so they go first and never repeat.
		self._page(synced=False, after="")
		if self._is_accounting_readable():
			self._page_synced()
		if self.seen:
			skipped = sum(result is SKIPPED for result in self.results)
			frappe.logger("central").info(
				f"GST state backfill: {len(self.results) - skipped} recorded, {skipped} skipped, "
				f"{self.seen - len(self.results)} failed"
			)

	def _page_synced(self) -> None:
		"""Synced invoices that cannot be read stay unrecorded, so each run starts after the
		last one the previous run read, and starts over once it reaches the end."""
		cache = frappe.cache()
		after = self._page(synced=True, after=cache.get_value(CURSOR_KEY) or "")
		cache.set_value(CURSOR_KEY, after)

	def _page(self, synced: bool, after: str) -> str:
		"""Record invoices after `after` until the run's cap; the last name read, or "" at the end."""
		while self.seen < MAX_PER_RUN:
			limit = min(PAGE, MAX_PER_RUN - self.seen)
			names = _unrecorded_invoices(after, limit, synced=synced)
			if not names:
				return ""
			self.results += each_isolated("GST state backfill", "Invoice", names, self.record)
			self.seen += len(names)
			if synced and self.is_accounting_down:
				return after
			after = names[-1]
		return after

	def record(self, invoice: str):
		"""Record one invoice's state and return it, or SKIPPED."""
		inv = frappe.db.get_value(
			"Invoice", invoice, ["name", "team", "erpnext_invoice", "creation"], as_dict=True
		)
		if inv.erpnext_invoice:
			state = self._filed_state(inv)
		else:
			state = state_at_issue(inv)
		if state is SKIPPED:
			return SKIPPED
		frappe.db.set_value(
			"Invoice", invoice, {"gst_state": state, "gst_state_recorded": 1}, update_modified=False
		)
		return state

	def _filed_state(self, inv):
		"""The state the invoice's Sales Invoice names, None if it names none, or SKIPPED."""
		if not self._is_accounting_readable():
			return SKIPPED
		try:
			record = connection.fetch("Sales Invoice", inv.erpnext_invoice)
		except (requests.RequestException, connection.NoAccess):
			self.is_accounting_down = True
			return SKIPPED
		if record is None:
			frappe.logger("central").warning(f"GST state backfill: the filing of {inv.name} is missing")
			return SKIPPED
		return _state_in_filing(inv.name, record.place_of_supply or "")

	def _is_accounting_readable(self) -> bool:
		return not self.is_accounting_down and connection.enabled()


def _state_in_filing(invoice: str, place_of_supply: str):
	"""The state a place of supply names, None if it names none, or SKIPPED if it cannot be read."""
	if not place_of_supply.strip():
		return None
	state = state_for_place_of_supply(place_of_supply)
	if state is None:
		# Recording no state would file it as IGST, which is a guess.
		frappe.logger("central").warning(f"GST state backfill: unknown place of supply on {invoice}")
		return SKIPPED
	return state


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


def _unrecorded_invoices(after: str, limit: int, synced: bool) -> list[str]:
	"""Issued INR invoices that charged GST and have no state recorded, by name after `after`."""
	invoice = frappe.qb.DocType("Invoice")
	is_unsynced = invoice.erpnext_invoice.isnull() | (invoice.erpnext_invoice == "")
	return (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(is_unsynced.negate() if synced else is_unsynced)
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
