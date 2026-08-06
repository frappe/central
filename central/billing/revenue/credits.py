# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit ledger — the customer's prepaid wallet (issue #06).

Every credit movement is an append-only Credit Ledger Entry (the audit trail).
Bookings serialise on a Credit Wallet anchor row via `SELECT ... FOR UPDATE`: a
concurrent booking for the same wallet blocks on that single primary-key row
until the prior transaction commits — closing the concurrent double-spend race.

The wallet is keyed **(team, currency)**, one anchor per currency a team holds
([ADR 0018](../../../../docs/adr/0018-invariants-are-enforced-not-observed.md)).
It was once keyed by team alone, with a single currency-blind `balance`: the
invoice waterfall read a *per-currency* balance off the ledger but debited the
*currency-blind* anchor, so a team holding two currencies could be driven
negative in one of them while the anchor stayed positive. The composite key makes
"the balance is never negative" true **per currency**, and the `CHECK (balance >=
0)` constraint on the column makes it true against every caller, not only the
polite ones.

Promotional credit expires; purchased credit does not. The wallet still holds one
balance, so "which credit is this?" is answered by replaying the ledger rather than
by a second column — see the expiry section at the foot of this module.

The balance is read and written ON the locked anchor row, not via a `FOR UPDATE`
on the ledger. An earlier version read the latest balance with
`... ORDER BY creation DESC LIMIT 1 FOR UPDATE`, which took a next-key lock on
the HEAD of the global `creation` index — the gap every team's INSERT lands in —
so bookings for *different* teams deadlocked there despite each holding only its
own wallet lock. Locking a single PK row takes no gap locks, so bookings for
different wallets never contend. The anchor's `balance` stays in lockstep with
the newest ledger entry's `running_balance` **for that currency**; the ledger
remains the audit truth.
"""

import random
import time

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum

from central.billing.catalog.entitlements import team_currency

# Bookings serialise on the wallet lock, but a busy InnoDB can still surface a
# transient cross-transaction deadlock; the loser rolls back and retries.
_DEADLOCK_RETRIES = 6
_DEADLOCK_BACKOFF = 0.05  # seconds; scaled by attempt + jitter


class InsufficientCredits(frappe.ValidationError):
	"""A debit would drive the wallet negative."""


def _backoff(attempt: int) -> None:
	"""Wait before retrying a deadlocked booking, jittered so retriers don't
	re-collide in lockstep."""
	time.sleep(_DEADLOCK_BACKOFF * (attempt + 1) + random.uniform(0, _DEADLOCK_BACKOFF))


def wallet_name(team: str, currency: str) -> str:
	"""The anchor's primary key — mirrors the `format:{team}-{currency}` autoname."""
	return f"{team}-{currency}"


def _resolve_currency(team: str, currency: str | None) -> str:
	"""The currency a credit movement is denominated in.

	Defaults to the team's billing currency (Billing Profile — the source of truth,
	locked after first money activity) rather than a hardcoded INR, so a USD team's
	wallet is never booked in the wrong currency by an omitted argument.
	"""
	return currency or team_currency(team)


def _ensure_wallet(team: str, currency: str):
	"""Create the (team, currency) wallet anchor if absent (race-safe on the PK)."""
	if frappe.db.exists("Credit Wallet", wallet_name(team, currency)):
		return
	try:
		frappe.get_doc({"doctype": "Credit Wallet", "team": team, "currency": currency}).insert(
			ignore_permissions=True
		)
	except frappe.DuplicateEntryError:
		pass  # a concurrent booking created it first — fine


def _lock_and_read_balance(team: str, currency: str) -> float:
	"""Lock the (team, currency) wallet anchor and return its current balance.

	A locking read (`FOR UPDATE`) on the single PK row: it both takes the per-wallet
	serialization lock (held until the caller commits) AND reads the *latest
	committed* balance, bypassing this transaction's REPEATABLE-READ snapshot
	(which a concurrent prior booking has since moved past). Because it targets one
	primary-key row it takes no gap locks, so different wallets never contend.

	The lock is taken on the PRIMARY KEY (`name` = `{team}-{currency}` under the
	`format:` autoname), NOT a secondary index. A secondary-index locking read locks
	the index record then the clustered record, the OPPOSITE order from the INSERT
	that creates the wallet (clustered then secondary) and from the `set_value`
	UPDATE (clustered only) — an opposite-order cycle some InnoDB versions deadlock
	on. Locking the clustered record directly keeps every path on one lock in one
	order. This reasoning is why the composite key lives in the *name*: it keeps the
	lock on the clustered PK instead of moving it to a secondary (team, currency)
	index, which would reintroduce exactly the deadlock this design exists to avoid.
	"""
	wallet = frappe.qb.DocType("Credit Wallet")
	rows = (
		frappe.qb.from_(wallet)
		.select(wallet.balance)
		.where(wallet.name == wallet_name(team, currency))
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
	gateway_payment_id: str | None = None,
	expires_on=None,
):
	"""Append one ledger entry under the per-wallet lock, retrying on deadlock.

	The wallet FOR UPDATE serialises bookings against the same (team, currency),
	but a busy InnoDB can still raise a transient deadlock (`QueryDeadlockError`)
	under heavy cross-transaction contention — InnoDB picks a victim and rolls its
	transaction back. The canonical remedy is to roll back and retry: each retry
	re-locks the wallet and re-reads the now-current balance, so the
	double-spend / InsufficientCredits guards still hold. `InsufficientCredits`
	and bad-amount errors are NOT retried — they are deterministic outcomes.

	`gateway_payment_id` (top-ups) makes the booking idempotent on the gateway
	payment: the synchronous confirm callback and the async webhook race to credit
	the SAME payment, so exactly one must win. The wallet lock serialises them and
	the under-lock pre-check in `_book_entry_once` skips the duplicate; the unique
	index on the column is the belt-and-braces backstop — if a second insert still
	reaches the DB it raises DuplicateEntryError, which we treat as "already
	credited" and return the winning entry rather than double-booking.
	"""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Credit amount must be positive.", frappe.ValidationError)
	currency = _resolve_currency(team, currency)

	for attempt in range(_DEADLOCK_RETRIES):
		try:
			return _book_entry_once(
				team,
				entry_type,
				amount,
				currency,
				reference_type,
				reference_name,
				note,
				gateway_payment_id,
				expires_on,
			)
		except frappe.QueryDeadlockError:
			# The transaction is already rolled back by InnoDB; sync Frappe's state
			# and back off before trying again.
			frappe.db.rollback()
			if attempt == _DEADLOCK_RETRIES - 1:
				raise
			_backoff(attempt)
		except frappe.DuplicateEntryError:
			# Lost the race on the gateway_payment_id unique key — the other path
			# (confirm callback or a replayed webhook) already credited this exact
			# payment. Roll back our half-built entry (balance bump included) and
			# return the winner; the payment books exactly one credit.
			frappe.db.rollback()
			return _existing_payment_entry(gateway_payment_id)


def _book_entry_once(
	team: str,
	entry_type: str,
	amount: float,
	currency: str,
	reference_type: str | None,
	reference_name: str | None,
	note: str | None,
	gateway_payment_id: str | None = None,
	expires_on=None,
):
	"""One booking attempt under the per-wallet lock; returns (doc, new_balance)."""
	_ensure_wallet(team, currency)
	balance = _lock_and_read_balance(team, currency)

	# Idempotency for top-ups: the wallet FOR UPDATE above serialises the confirm
	# callback and the webhook for this (same-team) payment, and a consistent read
	# taken AFTER acquiring the lock sees the winner's committed row — so if this
	# payment is already credited, return that entry instead of booking a second.
	if gateway_payment_id:
		existing = frappe.db.get_value(
			"Credit Ledger Entry", {"gateway_payment_id": gateway_payment_id}, "name"
		)
		if existing:
			return frappe.get_doc("Credit Ledger Entry", existing), balance

	return _post_entry(
		team,
		entry_type,
		amount,
		currency,
		balance,
		reference_type=reference_type,
		reference_name=reference_name,
		note=note,
		gateway_payment_id=gateway_payment_id,
		expires_on=expires_on,
	)


def _post_entry(
	team: str,
	entry_type: str,
	amount: float,
	currency: str,
	balance: float,
	reference_type: str | None = None,
	reference_name: str | None = None,
	note: str | None = None,
	gateway_payment_id: str | None = None,
	expires_on=None,
):
	"""Append one entry against an already-locked wallet; returns (doc, new_balance).

	The caller must hold the wallet lock and pass the balance it read under it — this
	is the half of a booking that moves money, split out so the expiry sweep can book
	several entries under one lock instead of re-taking it per entry.
	"""
	new_balance = balance + (amount if entry_type == "Credit" else -amount)
	if new_balance < 0:
		raise InsufficientCredits(
			f"Debit of {amount} {currency} exceeds wallet balance {balance} for {team}."
		)

	# Advance the authoritative balance on the locked anchor, then append the
	# immutable ledger entry mirroring it. Both commit together under the lock.
	# `set_value` skips the controller, so the guard above is the only application-
	# level check — the CHECK (balance >= 0) constraint on the column is what makes
	# a negative balance impossible for callers that never reach this function.
	frappe.db.set_value(
		"Credit Wallet",
		wallet_name(team, currency),
		"balance",
		new_balance,
		update_modified=False,
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
			"gateway_payment_id": gateway_payment_id,
			"expires_on": expires_on,
			"note": note,
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return entry, new_balance


def _existing_payment_entry(gateway_payment_id: str | None):
	"""Return (entry, balance) for an already-booked gateway payment — the winner
	of a confirm-vs-webhook race. Used when our own insert lost the unique key."""
	name = gateway_payment_id and frappe.db.get_value(
		"Credit Ledger Entry", {"gateway_payment_id": gateway_payment_id}, "name"
	)
	if not name:
		# Duplicate fired but the row is gone (or no id) — nothing to return to.
		frappe.throw("Credit booking conflicted but no prior entry found.", frappe.ValidationError)
	entry = frappe.get_doc("Credit Ledger Entry", name)
	balance = frappe.db.get_value("Credit Wallet", wallet_name(entry.team, entry.currency), "balance")
	return entry, frappe.utils.flt(balance)


def _namespaced_payment_id(gateway: str | None, payment_id: str | None) -> str | None:
	"""Prefix a gateway payment id with its provider so the stored key is unique
	across gateways, not just within one.

	A payment id is only guaranteed unique inside its own gateway — a Stripe id and
	a Razorpay id can be the same string yet mean two different payments. Storing
	`{gateway}:{payment_id}` keeps those apart, so the unique key never rejects a
	real second payment. The confirm callback, the pilot poll and the capture webhook
	all pass the same provider for a given payment, so they still dedupe to one credit.
	"""
	if not payment_id:
		return None
	return f"{gateway}:{payment_id}" if gateway else payment_id


def purchase(
	team: str,
	amount: float,
	currency: str | None = None,
	payment_method: str | None = None,
	reference_name: str | None = None,
	note: str | None = None,
	gateway_payment_id: str | None = None,
	gateway: str | None = None,
) -> dict:
	"""Top-up: book a credit entry for purchased credits.

	(The card charge that funds the top-up is the payment flow's concern; this
	books the resulting advance-liability credit.)

	`gateway_payment_id` dedupes a gateway-order top-up: the synchronous confirm
	callback and the async `payment.captured` webhook both call this for the same
	payment, and the unique-key + under-lock guard ensure it books one credit.
	`gateway` (the provider/adapter key) namespaces that id so ids only unique within
	a gateway can't collide across gateways — see `_namespaced_payment_id`.
	"""
	entry, new_balance = _book_entry(
		team,
		"Credit",
		amount,
		currency,
		reference_type="Payment Method" if payment_method else "Top-up",
		reference_name=payment_method or reference_name,
		note=note or "Credit top-up",
		gateway_payment_id=_namespaced_payment_id(gateway, gateway_payment_id),
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def apply_credit(team, amount, currency=None, reference_type=None, reference_name=None, note=None) -> dict:
	"""Debit the (team, currency) wallet (e.g. credits applied to an open invoice).

	Raises InsufficientCredits rather than going negative — per currency, since the
	anchor it debits is the same one the caller read. The waterfall logic that
	decides *how much* to apply against a card backstop lives in #11; this is the
	locked primitive it builds on.
	"""
	entry, new_balance = _book_entry(team, "Debit", amount, currency, reference_type, reference_name, note)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def refund_to_wallet(
	team, amount, currency=None, reference_type=None, reference_name=None, note=None
) -> dict:
	"""Book a credit entry for a partial-overcharge / gateway refund to wallet."""
	entry, new_balance = _book_entry(
		team, "Credit", amount, currency, reference_type, reference_name, note or "Refund to wallet"
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def promotional_expiry_date(on_date=None):
	"""When a promotional credit granted today stops being usable.

	`None` when the configured validity is 0 — the grant never expires, same as
	purchased credit."""
	from central.billing import settings

	days = settings.promotional_credit_validity_days()
	if not days:
		return None
	return frappe.utils.add_days(on_date or frappe.utils.nowdate(), days)


def grant_promotional_credits(team, amount, currency, note=None, expires_on=None) -> dict:
	"""Book a promotional/welcome credit — free credits granted at signup.

	Tagged `reference_type="Promotion"` so the one-time signup grant is
	distinguishable from top-ups/refunds and can be checked for idempotently.

	Promotional credit is the only kind that expires, and the date is stamped on the
	entry at grant time rather than derived from the setting when it is read. A team
	granted credit under a 90-day policy keeps its 90 days when the policy changes to
	60 — what a customer was given is a fact about that grant, not a live lookup."""
	entry, new_balance = _book_entry(
		team,
		"Credit",
		amount,
		currency,
		reference_type="Promotion",
		note=note or "Welcome credits",
		expires_on=expires_on if expires_on is not None else promotional_expiry_date(),
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def adjust_credits(
	team: str, amount: float, entry_type: str, currency: str | None = None, note: str | None = None
) -> dict:
	"""Admin manual correction — a credit or debit entry with an audit note."""
	if entry_type not in ("Credit", "Debit"):
		frappe.throw("entry_type must be 'Credit' or 'Debit'.", frappe.ValidationError)
	entry, new_balance = _book_entry(
		team, entry_type, amount, currency, reference_type="Admin", note=note or "Admin adjustment"
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def get_balance(team: str, currency: str | None = None, source=None) -> dict:
	"""The team's credit balance in one currency — read off that currency's anchor.

	`source` is the projection seam. A projection that has already spent this wallet
	down over three simulated months must not be answered with today's balance, or the
	wallet silently refills every month and nobody is ever short. Pass an object with
	`balance(team, currency)` and the reader defers to it; leave it out — as every
	production caller does — and nothing changes.

	`currency` defaults to the team's billing currency, so the common caller
	("what are this team's credits?") gets the balance in the currency the team is
	actually billed in. There is deliberately no "overall balance" across
	currencies: summing INR and USD floats produced a number that meant nothing and
	that the debit path then enforced its non-negative guard against. Use
	`get_balances` for the multi-currency view.

	Reads the anchor, not the ledger — the anchor is the authoritative balance
	(maintained under its row lock) and the ledger is the audit trail. The two are
	reconciled by the C2 invariant check, not by disagreeing at read time.
	"""
	currency = _resolve_currency(team, currency)
	if source is not None:
		return {"balance": frappe.utils.flt(source.balance(team, currency)), "currency": currency}
	balance = frappe.db.get_value("Credit Wallet", wallet_name(team, currency), "balance")
	return {"balance": frappe.utils.flt(balance), "currency": currency}


def get_balances(team: str) -> list[dict]:
	"""Every currency this team holds credits in — never summed across currencies."""
	return frappe.get_all(
		"Credit Wallet",
		filters={"team": team},
		fields=["currency", "balance"],
		order_by="currency asc",
	)


def ledger_balance(team: str, currency: str) -> float:
	"""The balance implied by the append-only ledger, summed from the entries.

	The independent second opinion the anchor is checked against (invariant C2,
	[ADR 0018]). Not a read path — nothing in the write path should call this.
	"""
	cle = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(cle.entry_type == "Credit", cle.amount).else_(-cle.amount)
	balance = (
		frappe.qb.from_(cle).select(Sum(signed)).where((cle.team == team) & (cle.currency == currency)).run()
	)[0][0]
	return frappe.utils.flt(balance)


# --- expiry -------------------------------------------------------------------
#
# Purchased credit never expires; promotional credit does, and carries the date it
# was granted under (`expires_on`). Expiring it means answering "how much of THIS
# grant is left?", which the ledger does not store — it stores movements, and the
# wallet stores one number. So the answer is derived: debits are applied to credits
# soonest-expiry-first, and whatever is still sitting in a grant when its date
# passes is swept out with an offsetting Debit.
#
# Soonest-expiry-first is what makes the customer whole. Spending the credit that is
# about to die before the credit that never will is the order that wastes the least,
# and it is what every provider that grants expiring credit does. It also keeps the
# sweep simple: the grant that expires next is always the one at the front of the
# queue, so expiring it is exactly "consume what remains of the front lot".


def credit_lots(team: str, currency: str) -> list[dict]:
	"""Every credit booking on this wallet, with how much of each is left.

	Derived by replaying the ledger: debits are drawn against credits in
	(expiry, then age) order, so a grant expiring on Friday is spent before one
	expiring next month, and both before credit that never expires.

	The remainders sum to the wallet balance — this is the same money, sliced by
	where it came from rather than totalled.
	"""
	import datetime

	cle = frappe.qb.DocType("Credit Ledger Entry")
	rows = (
		frappe.qb.from_(cle)
		.select(cle.name, cle.entry_type, cle.amount, cle.expires_on, cle.creation)
		.where((cle.team == team) & (cle.currency == currency))
		.orderby(cle.creation)
		.run(as_dict=True)
	)

	lots = [row for row in rows if row.entry_type == "Credit"]
	unspent = sum(frappe.utils.flt(row.amount) for row in rows if row.entry_type == "Debit")
	lots.sort(
		key=lambda lot: (
			frappe.utils.getdate(lot.expires_on) if lot.expires_on else datetime.date.max,
			lot.creation,
		)
	)
	for lot in lots:
		spent = min(frappe.utils.flt(lot.amount), unspent)
		unspent -= spent
		lot.remaining = frappe.utils.flt(lot.amount) - spent
	return lots


def expiring_credits(team: str, currency: str | None = None, on_date=None) -> list[dict]:
	"""Unspent promotional credit that still has an expiry date ahead of it.

	What the customer is shown as "expiring soon" — one row per grant, soonest first.
	Grants already past their date are not included: the sweep books them out, and
	until it runs they are not the customer's to spend anyway.
	"""
	currency = _resolve_currency(team, currency)
	on_date = frappe.utils.getdate(on_date)
	return [
		{"amount": lot.remaining, "expires_on": lot.expires_on, "ledger_entry": lot.name}
		for lot in credit_lots(team, currency)
		if lot.expires_on and lot.remaining > 0 and frappe.utils.getdate(lot.expires_on) > on_date
	]


def expire_credits(team: str, currency: str, on_date=None) -> list[dict]:
	"""Sweep every expired grant off one wallet; returns what was written off.

	Runs under the wallet lock, and the remainders are computed *inside* it: reading
	them first and booking after would let a concurrent invoice settlement spend the
	same credit we are writing off, and the wallet would be debited twice for money
	that existed once.

	Idempotent by construction rather than by a flag. The sweep's own Debit consumes
	the grant it settles, so a second run finds nothing left in it and writes nothing.
	"""
	on_date = frappe.utils.getdate(on_date)
	for attempt in range(_DEADLOCK_RETRIES):
		try:
			return _expire_credits_once(team, currency, on_date)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == _DEADLOCK_RETRIES - 1:
				raise
			_backoff(attempt)
	return []


def _expire_credits_once(team: str, currency: str, on_date) -> list[dict]:
	"""One sweep attempt: lock the wallet, then write off what has run out of time."""
	_ensure_wallet(team, currency)
	balance = _lock_and_read_balance(team, currency)

	expired = []
	for lot in credit_lots(team, currency):
		if not lot.expires_on or lot.remaining <= 0:
			continue
		if frappe.utils.getdate(lot.expires_on) > on_date:
			break  # lots are in expiry order, so nothing after this has expired either
		entry, balance = _post_entry(
			team,
			"Debit",
			lot.remaining,
			currency,
			balance,
			reference_type="Expiry",
			reference_name=lot.name,
			note=f"Promotional credit expired on {lot.expires_on}",
		)
		expired.append({"ledger_entry": entry.name, "amount": lot.remaining, "expired_grant": lot.name})
	return expired


def run_credit_expiry(on_date=None) -> dict:
	"""Daily: write off promotional credit that has run out of time.

	Scans only wallets that hold a grant already past its date — a team whose credit
	never expires is never looked at.
	"""
	on_date = frappe.utils.getdate(on_date)
	cle = frappe.qb.DocType("Credit Ledger Entry")
	wallets = (
		frappe.qb.from_(cle)
		.select(cle.team, cle.currency)
		.distinct()
		.where((cle.entry_type == "Credit") & cle.expires_on.isnotnull() & (cle.expires_on <= on_date))
		.run(as_dict=True)
	)

	swept, total = 0, 0.0
	for wallet in wallets:
		# A wallet with nothing in it has nothing to expire; skip before taking a lock.
		if (
			frappe.utils.flt(
				frappe.db.get_value("Credit Wallet", wallet_name(wallet.team, wallet.currency), "balance")
			)
			<= 0
		):
			continue
		for expiry in expire_credits(wallet.team, wallet.currency, on_date):
			swept += 1
			total += expiry["amount"]
			frappe.logger("billing").info(
				f"expired {expiry['amount']} {wallet.currency} of promotional credit "
				f"for {wallet.team} (grant {expiry['expired_grant']})"
			)

	return {"wallets": len(wallets), "entries": swept, "amount": total}
