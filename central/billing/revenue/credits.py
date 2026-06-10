# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit ledger — the customer's prepaid wallet (issue #06).

Every credit movement is an append-only Credit Ledger Entry (the audit trail).
Bookings serialise on a per-team Credit Wallet anchor row via `SELECT ... FOR
UPDATE`: a concurrent booking for the same team blocks on that single
primary-key row until the prior transaction commits — closing the concurrent
double-spend race.

The balance is read and written ON the locked anchor row, not via a `FOR UPDATE`
on the ledger. An earlier version read the latest balance with
`... ORDER BY creation DESC LIMIT 1 FOR UPDATE`, which took a next-key lock on
the HEAD of the global `creation` index — the gap every team's INSERT lands in —
so bookings for *different* teams deadlocked there despite each holding only its
own wallet lock. Locking a single PK row (per team) takes no gap locks, so
cross-team bookings never contend. The anchor's `balance` stays in lockstep with
the newest ledger entry's `running_balance`; the ledger remains the audit truth.
"""

import random
import time

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum

# Bookings serialise on the wallet lock, but a busy InnoDB can still surface a
# transient cross-transaction deadlock; the loser rolls back and retries.
_DEADLOCK_RETRIES = 6
_DEADLOCK_BACKOFF = 0.05  # seconds; scaled by attempt + jitter


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


def _lock_and_read_balance(team: str) -> float:
	"""Lock the team's wallet anchor and return its current balance.

	A locking read (`FOR UPDATE`) on the single PK row: it both takes the per-team
	serialization lock (held until the caller commits) AND reads the *latest
	committed* balance, bypassing this transaction's REPEATABLE-READ snapshot
	(which a concurrent prior booking has since moved past). Because it targets one
	primary-key row it takes no gap locks, so different teams never contend.

	The lock is taken on the PRIMARY KEY (`name`, which equals `team` under the
	`field:team` autoname), NOT the secondary unique `team` index. A secondary-index
	locking read locks the index record then the clustered record, the OPPOSITE
	order from the INSERT that creates the wallet (clustered then unique index) and
	from the `set_value` UPDATE (clustered only) — an opposite-order cycle some
	InnoDB versions deadlock on. Locking the clustered record directly keeps every
	path on one lock in one order.
	"""
	wallet = frappe.qb.DocType("Credit Wallet")
	rows = (
		frappe.qb.from_(wallet)
		.select(wallet.balance)
		.where(wallet.name == team)
		.for_update()
		.run(pluck=True)
	)
	return frappe.utils.flt(rows[0]) if rows else 0.0


def _book_entry(
	team: str,
	entry_type: str,
	amount,
	currency: str,
	reference_type: str | None = None,
	reference_name: str | None = None,
	note: str | None = None,
):
	"""Append one ledger entry under the per-team lock, retrying on deadlock.

	The wallet FOR UPDATE serialises same-team bookings, but a busy InnoDB can
	still raise a transient deadlock (`QueryDeadlockError`) under heavy
	cross-transaction contention — InnoDB picks a victim and rolls its
	transaction back. The canonical remedy is to roll back and retry: each retry
	re-locks the wallet and re-reads the now-current balance, so the
	double-spend / InsufficientCredits guards still hold. `InsufficientCredits`
	and bad-amount errors are NOT retried — they are deterministic outcomes.
	"""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Credit amount must be positive.", frappe.ValidationError)

	for attempt in range(_DEADLOCK_RETRIES):
		try:
			return _book_entry_once(
				team, entry_type, amount, currency, reference_type, reference_name, note
			)
		except frappe.QueryDeadlockError:
			# The transaction is already rolled back by InnoDB; sync Frappe's state
			# and back off (jittered) so retriers don't re-collide in lockstep.
			frappe.db.rollback()
			if attempt == _DEADLOCK_RETRIES - 1:
				raise
			time.sleep(_DEADLOCK_BACKOFF * (attempt + 1) + random.uniform(0, _DEADLOCK_BACKOFF))


def _book_entry_once(
	team: str,
	entry_type: str,
	amount: float,
	currency: str,
	reference_type: str | None,
	reference_name: str | None,
	note: str | None,
):
	"""One booking attempt under the per-team lock; returns (doc, new_balance)."""
	_ensure_wallet(team, currency)
	balance = _lock_and_read_balance(team)
	new_balance = balance + (amount if entry_type == "credit" else -amount)
	if new_balance < 0:
		raise InsufficientCredits(
			f"Debit of {amount} exceeds wallet balance {balance} for {team}."
		)

	# Advance the authoritative balance on the locked anchor, then append the
	# immutable ledger entry mirroring it. Both commit together under the lock.
	frappe.db.set_value("Credit Wallet", team, "balance", new_balance, update_modified=False)
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
	"""Current wallet balance for the team, optionally filtered to one currency.

	When `currency` is supplied only entries in that currency are summed — useful
	once a team holds credits in multiple currencies. `running_balance` is a
	single currency-blind cumulative, so a per-currency read must sum that
	currency's signed amounts rather than read the newest matching row's
	`running_balance` (which carries the team's overall balance at that point).
	When omitted the overall balance is the newest entry's running_balance
	(backward-compatible while teams are single-currency).
	"""
	if currency:
		cle = frappe.qb.DocType("Credit Ledger Entry")
		signed = Case().when(cle.entry_type == "credit", cle.amount).else_(-cle.amount)
		balance = (
			frappe.qb.from_(cle)
			.select(Sum(signed))
			.where((cle.team == team) & (cle.currency == currency))
			.run()
		)[0][0]
		return {"balance": frappe.utils.flt(balance), "currency": currency}

	balance = frappe.db.get_value(
		"Credit Ledger Entry",
		{"team": team},
		"running_balance",
		order_by="creation desc, name desc",
	)
	return {"balance": frappe.utils.flt(balance), "currency": currency}
