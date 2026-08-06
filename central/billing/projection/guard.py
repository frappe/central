# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The projection's licence to run against production data: it cannot write.

That guarantee is a database one, not a code-review one. Every projection executes
inside `START TRANSACTION READ ONLY`, so an `INSERT`/`UPDATE`/`DELETE` at *any* call
depth fails in MariaDB (error 1792) instead of being caught by whoever reviews the
diff. This matters because the engine deliberately calls into `revenue/`, `catalog/`
and `payments/` — modules that do write — so a guard that only inspected this package
would prove nothing about what runs three frames down.

The transaction only sees the database. Redis and HTTP go around it — `enqueue` is
the dangerous one, since the job it schedules runs later on a fresh, writable
connection — so those are held by a separate test that greps for them.

Scope: this wraps the *engine*, not the request. Saving a projection is a write, and
it happens afterwards in an ordinary transaction.
"""

from contextlib import contextmanager

import frappe


class ProjectionWroteError(frappe.ValidationError):
	"""A projection reached a write.

	Not a user error and not a permissions problem — the decision half of some billing
	act still has an effect welded to it, and the fix is in that seam.
	"""


@contextmanager
def read_only():
	"""Run a block inside a read-only transaction, and name what happens if it writes.

	Assumes the caller has nothing uncommitted: `START TRANSACTION` implicitly commits
	an open transaction, so this belongs at the top of a read endpoint rather than in
	the middle of unfinished work.
	"""
	previous = frappe.flags.read_only
	frappe.flags.read_only = True
	frappe.db.begin(read_only=True)
	try:
		yield
	except frappe.InReadOnlyMode as e:
		raise ProjectionWroteError(
			"A projection attempted to write. Projections read; the billing run writes."
		) from e
	finally:
		# Clear the flag BEFORE rolling back, and not for tidiness: `rollback()` ends
		# the transaction and immediately calls `begin()`, which reads this same flag.
		# Restore it afterwards and the *next* transaction is read-only too — the guard
		# leaks, and every write for the rest of the request fails somewhere unrelated.
		frappe.flags.read_only = previous
		# Releases the consistent snapshot. Rollback rather than commit: nothing was
		# meant to change, so there is nothing to keep, and a long-held snapshot pins
		# the undo log for every other query on the box.
		frappe.db.rollback()
