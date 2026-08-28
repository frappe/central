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

	def validate(self):
		self.set_period_key()

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
