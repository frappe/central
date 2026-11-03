# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Invoice — postpaid, in-arrears, immutable once issued.

Naming is INV-YYYY-MM-NNNNN keyed on the billing month (period_end). Line items
are generated once and never updated; corrections are by state (cancel+reissue
before payment; refund / wallet credit after), never by mutation.

`period_key` enforces the invariant a billing system may not get wrong: **a team is
billed at most once for a period** (ADR 0018, invariant I6). It is a derived column
with a unique index, so a second bill for the same (team, period) is refused by the
database rather than by whoever remembered to check first. A team's Project tags
show up as a breakdown on the invoice's own line items (`Invoice Line Item.project`),
not as separate invoices.
"""

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

CANCELLED = "Cancelled"
OUTSTANDING = "Outstanding"
# What a team still owes; leaving one of these is when dunning can let go.
UNSETTLED = (OUTSTANDING, "Overdue")


# An invoice is issued when collection starts and sets its due date. Before that it is
# held: it is never charged, dunned or counted as owed. Overdue is reached only from an
# issued invoice, so it always has a due date.
def is_issued(invoice) -> bool:
	return bool(invoice.get("due_date"))


def is_owed(invoice) -> bool:
	"""Issued and not settled: what the customer owes."""
	return invoice.status in UNSETTLED and is_issued(invoice)


def issued_filters() -> list[list]:
	"""Invoices collection has started on, settled ones included."""
	return [["due_date", "is", "set"]]


def owed_filters() -> list[list]:
	"""Invoices the customer owes: issued and not settled."""
	return [["status", "in", UNSETTLED], *issued_filters()]


def is_unissued(invoice) -> bool:
	"""`unissued_filters` for one invoice."""
	return invoice.status == OUTSTANDING and not is_issued(invoice)


def unissued_filters() -> list[list]:
	"""Outstanding invoices that collection has not started on yet."""
	return [["status", "=", OUTSTANDING], ["due_date", "is", "not set"]]


def period_key_for(team: str, period_start, period_end) -> str:
	"""The live-invoice slot for a (team, period).

	The one place the key's format is spelled out — the controller derives it on every
	save and the backfill patch rewrites history with it, and those two must never
	disagree about what occupies a slot.
	"""
	return f"{team}|{period_start}|{period_end}"


class Invoice(Document):
	def autoname(self):
		month = frappe.utils.getdate(self.period_end or frappe.utils.nowdate())
		self.name = make_autoname(f"INV-{month.year:04d}-{month.month:02d}-.#####")

	def onload(self):
		# The form offers a retry when a gateway refused one of this invoice's refunds.
		self.set_onload(
			"failed_refunds",
			frappe.db.count("Refund", {"invoice": self.name, "status": "Failed", "destination": "Source"}),
		)
		if self.status == "Paid":
			from central.billing.payments.corrections import card_refundable, refundable

			self.set_onload("refundable", refundable(self))
			self.set_onload("card_refundable", card_refundable(self.name))

	def validate(self):
		self.set_period_key()

	def update_child_table(self, fieldname, df=None):
		# A status save leaves the lines as they were, so they are not written again.
		if fieldname == "items" and self.has_unchanged_lines():
			return
		super().update_child_table(fieldname, df)

	def has_unchanged_lines(self) -> bool:
		"""The lines hold the same values as the saved invoice.

		The copy before save is read from the database, so any line added, removed or edited
		in memory makes the lists differ and the lines are written."""
		before = self.get_doc_before_save()
		if self.is_new() or not before:
			return False
		return _line_values(self.items) == _line_values(before.items)

	def on_update(self):
		self.restore_team_once_settled()

	def restore_team_once_settled(self):
		"""When an unpaid invoice is paid or waived, a team with no other overdue invoice is
		restored: standing back to Current and the servers dunning stopped started again. An
		Outstanding invoice does not hold the restore, since it is not yet overdue and dunning acts on
		it on its own schedule. A cancel does not restore: it is a correction, and the
		reissued invoice is still owed."""
		before = self.get_doc_before_save()
		if not before or before.status not in UNSETTLED or self.status not in ("Paid", "Waived"):
			return
		from central.billing.catalog.subscriptions import restore_after_payment
		from central.billing.payments.settlement import has_overdue_invoice

		if not has_overdue_invoice(self.team):
			restore_after_payment(self.team)

	def set_period_key(self):
		"""One live invoice per (team, period); cancelled ones step aside.

		A cancelled invoice takes a per-invoice sentinel rather than NULL. Frappe
		coerces an unset Data field to the empty string, and empty strings *collide*
		in a unique index — so "null it on cancel" would let the first cancellation
		through and reject the second. The sentinel is a total function: every invoice
		always has a key, and only live ones compete for the period's slot, so a
		cancel-and-reissue can reclaim it.
		"""
		if self.status == CANCELLED:
			self.period_key = f"{CANCELLED}|{self.name}"
		else:
			self.period_key = period_key_for(self.team, self.period_start, self.period_end)


def _line_values(rows) -> list[tuple]:
	fields = [df.fieldname for df in frappe.get_meta("Invoice Line Item").fields if df.fieldname]
	return [(row.name, tuple(row.get(f) for f in fields)) for row in rows]


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Invoice", ["period_end", "status"])
	frappe.db.add_index("Invoice", ["status", "invoice_type"])
	frappe.db.add_index("Invoice", ["erpnext_sync_status"])
