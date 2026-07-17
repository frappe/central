# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit Wallet — the (team, currency) lock anchor and authoritative balance.

The balance may never be negative. That invariant is enforced at three rungs,
deliberately (ADR 0018):

  1. `CHECK (balance >= 0)` on the column — the only rung that holds against every
     caller, including `frappe.db.set_value`, which skips this controller entirely
     (and is exactly how `credits.py` writes the balance).
  2. `validate` below — turns an ORM write into a clear message instead of an
     OperationalError from the constraint.
  3. The `InsufficientCredits` guard in `credits._book_entry_once`, under the row
     lock, which is what a caller actually sees.

Three rungs, because the failure this prevents is a customer's credit balance going
quietly negative — the v1 bug.
"""

import frappe
from frappe.model.document import Document


class CreditWallet(Document):
	def validate(self):
		if frappe.utils.flt(self.balance) < 0:
			frappe.throw(
				frappe._("Credit balance cannot be negative (got {0} {1} for team {2}).").format(
					self.balance, self.currency, self.team
				),
				frappe.ValidationError,
			)
