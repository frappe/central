# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit ledger — the customer's prepaid wallet (issue #06).

Every credit movement is an append-only Credit Ledger Entry. The balance is the
running sum, never a scalar on Team. Bookings serialise on a per-team Credit
Wallet anchor row via `SELECT ... FOR UPDATE`: a concurrent booking blocks on
that single primary-key row until the prior transaction commits, then reads the
now-current latest balance — closing the v1 concurrent double-spend race.

The lock is taken on the wallet anchor (a stable PK lookup) rather than on
"the latest ledger row": locking a moving `ORDER BY ... LIMIT 1` target while
others insert into the same index gap deadlocks under InnoDB next-key locking.
The anchor row carries no balance — the balance is still purely the ledger sum.
"""

import frappe


class InsufficientCredits(frappe.ValidationError):
	"""A debit would drive the wallet negative."""


def _ensure_wallet(team: str, currency: str | None = None):
	"""Create the team's wallet anchor if absent (race-safe on the unique key)."""
	if frappe.db.exists("Credit Wallet", team):
		return
	try:
		frappe.get_doc(
			{"doctype": "Credit Wallet", "team": team, "currency": currency}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass  # a concurrent booking created it first — fine


def _lock_wallet(team: str):
	"""Take the per-team serialization lock (held until the caller commits)."""
	frappe.db.sql("SELECT name FROM `tabCredit Wallet` WHERE team = %s FOR UPDATE", team)


def _current_balance(team: str):
	"""Latest running balance (0 if none), as a *current* read.

	Must run after `_lock_wallet`. A locking read (`FOR UPDATE`) is used rather
	than a plain SELECT so it reads the latest committed row instead of this
	transaction's REPEATABLE-READ snapshot (which was fixed earlier, before the
	wallet lock was held, and would otherwise miss a prior booking's commit).
	The wallet lock has already serialised bookings, so this row lock is
	contention-free — no deadlock.
	"""
	rows = frappe.db.sql(
		"""
		SELECT running_balance
		FROM `tabCredit Ledger Entry`
		WHERE team = %s
		ORDER BY creation DESC, name DESC
		LIMIT 1
		FOR UPDATE
		""",
		team,
		as_dict=True,
	)
	return frappe.utils.flt(rows[0].running_balance) if rows else 0.0


def _book_entry(
	team: str,
	entry_type: str,
	amount,
	currency: str,
	reference_type: str | None = None,
	reference_name: str | None = None,
	note: str | None = None,
):
	"""Append one ledger entry under the per-team lock and return (doc, new_balance)."""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Credit amount must be positive.", frappe.ValidationError)

	_ensure_wallet(team, currency)
	_lock_wallet(team)
	balance = _current_balance(team)
	new_balance = balance + (amount if entry_type == "credit" else -amount)
	if new_balance < 0:
		raise InsufficientCredits(
			f"Debit of {amount} exceeds wallet balance {balance} for {team}."
		)

	entry = frappe.get_doc(
		{
			"doctype": "Credit Ledger Entry",
			"team": team,
			"entry_type": entry_type,
			"amount": amount,
			"currency": currency,
			"running_balance": new_balance,
			"reference_type": reference_type,
			"reference_name": reference_name,
			"note": note,
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return entry, new_balance


@frappe.whitelist()
def purchase(team: str, amount: float, currency: str = "INR", payment_method: str | None = None,
			 reference_name: str | None = None, note: str | None = None) -> dict:
	"""Top-up: book a credit entry for purchased credits.

	(The card charge that funds the top-up is the payment flow's concern; this
	books the resulting advance-liability credit.)
	"""
	entry, new_balance = _book_entry(
		team,
		"credit",
		amount,
		currency,
		reference_type="Payment Method" if payment_method else "Top-up",
		reference_name=payment_method or reference_name,
		note=note or "Credit top-up",
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def apply_credit(
	team, amount, currency="INR", reference_type=None, reference_name=None, note=None
) -> dict:
	"""Debit the wallet (e.g. credits applied to an open invoice).

	Raises InsufficientCredits rather than going negative. The waterfall logic
	that decides *how much* to apply against a card backstop lives in #11; this
	is the locked primitive it builds on.
	"""
	entry, new_balance = _book_entry(
		team, "debit", amount, currency, reference_type, reference_name, note
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def refund_to_wallet(team, amount, currency="INR", reference_type=None, reference_name=None, note=None) -> dict:
	"""Book a credit entry for a partial-overcharge / gateway refund to wallet."""
	entry, new_balance = _book_entry(
		team, "credit", amount, currency, reference_type, reference_name, note or "Refund to wallet"
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


@frappe.whitelist()
def adjust_credits(team: str, amount: float, entry_type: str, currency: str = "INR",
				   note: str | None = None) -> dict:
	"""Admin manual correction — a credit or debit entry with an audit note."""
	if entry_type not in ("credit", "debit"):
		frappe.throw("entry_type must be 'credit' or 'debit'.", frappe.ValidationError)
	entry, new_balance = _book_entry(
		team, entry_type, amount, currency, reference_type="Admin", note=note or "Admin adjustment"
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


@frappe.whitelist()
def get_balance(team: str, currency: str | None = None) -> dict:
	"""Current wallet balance = the latest entry's running balance (0 if none).

	A plain read (no lock); equals the ledger sum by the running-balance
	invariant.
	"""
	balance = frappe.db.get_value(
		"Credit Ledger Entry",
		{"team": team},
		"running_balance",
		order_by="creation desc, name desc",
	)
	return {"balance": frappe.utils.flt(balance), "currency": currency}
