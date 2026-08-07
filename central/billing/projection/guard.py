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


class ProjectionBoundaryError(frappe.ValidationError):
	"""A projection was asked for in the middle of unfinished work."""


@contextmanager
def read_only(strict: bool = True):
	"""Run a block inside a read-only transaction, and name what happens if it writes.

	A projection is a transaction boundary. `START TRANSACTION` implicitly commits an
	open one, so entering with pending writes would silently commit somebody else's
	half-finished work — a side effect caused by asking a question, which is the exact
	class of accident this guard exists to prevent. Frappe refuses the implicit commit
	outright (`ImplicitCommitError`); we refuse earlier and say why. Deciding whether
	that pending work should be kept or discarded belongs to the caller, never here.

	In a request this never fires: a projection endpoint reads and writes nothing
	before it starts.
	"""
	if frappe.db.transaction_writes:
		if strict:
			raise ProjectionBoundaryError(
				"A projection cannot start with unsaved changes pending — commit or roll "
				"back first. Projections read a consistent snapshot and must not decide "
				"the fate of someone else's transaction."
			)
		# Non-strict callers are customer-facing reads that happen to share a request
		# with a write — the customer forecast, say. Refusing them would break a page to
		# enforce an internal invariant, and committing on their behalf is the side
		# effect this guard exists to prevent. So the read proceeds without the
		# transaction: the engine still cannot write, because the decision/effect split
		# and the grep hold that; what is given up is the database enforcing it too.
		frappe.logger("billing").debug(
			"projection ran unguarded: the caller had uncommitted changes"
		)
		yield
		return

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
