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
from frappe import _
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


def _group_ledger_sum(team: str, currency: str, billing_group: str) -> float:
	"""SUM(Credit) - SUM(Debit) for entries tagged this exact Billing Group.

	Read only, not a booking primitive. Called both by `group_budget` (the public,
	floored view) and by `_post_entry` (which needs the raw pre-entry sum, under the
	wallet lock, to decide whether a pending Debit fits)."""
	cle = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(cle.entry_type == "Credit", cle.amount).else_(-cle.amount)
	result = (
		frappe.qb.from_(cle)
		.select(Sum(signed))
		.where((cle.team == team) & (cle.currency == currency) & (cle.billing_group == billing_group))
		.run()
	)[0][0]
	return frappe.utils.flt(result)


def group_budget(team: str, currency: str, billing_group: str) -> float:
	"""Credit earmarked for this Billing Group and not yet spent by its own invoices.

	A computed subset of the ONE (team, currency) wallet — not a separate wallet.
	Only ledger entries explicitly tagged with this group count; a group invoice's
	settlement draws from this and ONLY this (see `lifecycle.open_and_collect`) —
	never the general pool, never another group's budget. Floored at zero: a
	negative raw sum would mean an entry booked ahead of the guard in `_post_entry`
	(a bug, not a spendable amount), and "how much can this group's invoice draw"
	should read 0, not negative.
	"""
	return max(0.0, _group_ledger_sum(team, currency, billing_group))


def _reserved_balance(team: str, currency: str) -> float:
	"""Sum of every currently-ENABLED Billing Group's remaining budget for this
	(team, currency) — the slice of the wallet earmarked and off-limits to the
	consolidated invoice and to every other group.

	Only enabled groups reserve: a disabled group's leftover tagged credit is
	excluded here, so it falls back into `general_pool_balance` automatically —
	no ledger transaction needed to "return" it. Re-enabling a group later starts
	its budget fresh (old tagged entries stay tagged, but a NEW group reservation
	begins from whatever fresh entries get tagged to it going forward — this
	function does not distinguish "was disabled" history, only current `enabled`).
	"""
	groups = frappe.get_all("Billing Group", filters={"team": team, "enabled": 1}, pluck="name")
	return sum(group_budget(team, currency, g) for g in groups)


def general_pool_balance(team: str, currency: str) -> float:
	"""What the team's consolidated invoice — and no group invoice — may draw.

	The (team, currency) wallet's real balance minus every enabled group's reserved
	budget. Reads the wallet without locking it (a plain read, like `get_balance`);
	the authoritative, lock-consistent version of this check happens again inside
	`_post_entry` under the wallet lock at the moment a Debit is actually posted.
	"""
	balance = frappe.db.get_value("Credit Wallet", wallet_name(team, currency), "balance")
	return max(0.0, frappe.utils.flt(balance) - _reserved_balance(team, currency))


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
	billing_group: str | None = None,
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
		frappe.throw(_("Credit amount must be positive."), frappe.ValidationError)
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
				billing_group,
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
	billing_group: str | None = None,
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
		billing_group=billing_group,
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
	billing_group: str | None = None,
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

	# A Debit is further scoped to its billing_group's own earmark — the wallet-level
	# check above only guards the TOTAL pot; it would happily let a group invoice
	# overdraw into money reserved for a *different* group, since physically it is
	# all one balance. This is the enforcement point for "isolated, no fallback":
	# the same trusted layer as the wallet guard, not something every caller must
	# remember to cap correctly. Reads under the wallet lock already held by
	# `_book_entry_once`, so no concurrent booking for this (team, currency) —
	# tagged or not — can be in flight while this reads.
	if entry_type == "Debit":
		if billing_group:
			available = _group_ledger_sum(team, currency, billing_group)
			if amount > available:
				raise InsufficientCredits(
					f"Debit of {amount} {currency} exceeds Billing Group {billing_group}'s "
					f"own budget {available} for {team} — group invoices draw only their "
					f"own earmarked credit, never the general pool or another group's."
				)
		else:
			pool = balance - _reserved_balance(team, currency)
			if amount > pool:
				raise InsufficientCredits(
					f"Debit of {amount} {currency} exceeds the general pool {pool} for {team} "
					"— the consolidated invoice draws only untagged credit, never a Billing "
					"Group's reserved budget."
				)

	# Advance the authoritative balance on the locked anchor, then append the
	# immutable ledger entry mirroring it. Both commit together under the lock.
	# `set_value` skips the controller, so the guards above are the only
	# application-level checks — the CHECK (balance >= 0) constraint on the column
	# is what makes a negative TOTAL balance impossible even for a caller that
	# bypasses this function; the per-scope guards above have no such DB backstop,
	# since the scoping is a ledger-tag concept the wallet table knows nothing about.
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
			"billing_group": billing_group,
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
		frappe.throw(_("Credit booking conflicted but no prior entry found."), frappe.ValidationError)
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
	billing_group: str | None = None,
) -> dict:
	"""Top-up: book a credit entry for purchased credits.

	(The card charge that funds the top-up is the payment flow's concern; this
	books the resulting advance-liability credit.)

	`gateway_payment_id` dedupes a gateway-order top-up: the synchronous confirm
	callback and the async `payment.captured` webhook both call this for the same
	payment, and the unique-key + under-lock guard ensure it books one credit.
	`gateway` (the provider/adapter key) namespaces that id so ids only unique within
	a gateway can't collide across gateways — see `_namespaced_payment_id`.

	`billing_group` earmarks this top-up to that group's budget instead of the
	general pool — e.g. a partner topping up specifically for one end-customer.
	Unset (the default) funds the general pool, same as before this existed.
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
		billing_group=billing_group,
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def apply_credit(
	team, amount, currency=None, reference_type=None, reference_name=None, note=None, billing_group=None
) -> dict:
	"""Debit the (team, currency) wallet (e.g. credits applied to an open invoice).

	Raises InsufficientCredits rather than going negative — per currency, since the
	anchor it debits is the same one the caller read. The waterfall logic that
	decides *how much* to apply against a card backstop lives in #11; this is the
	locked primitive it builds on.

	`billing_group` scopes the debit to that group's own earmarked budget — pass
	the invoice's own `billing_group` (None for the consolidated invoice). See
	`group_budget` / `general_pool_balance` for what each may draw; `_post_entry`
	is where that isolation is actually enforced, not this wrapper.
	"""
	entry, new_balance = _book_entry(
		team, "Debit", amount, currency, reference_type, reference_name, note, billing_group=billing_group
	)
	return {"ledger_entry": entry.name, "new_balance": new_balance}


def refund_to_wallet(
	team, amount, currency=None, reference_type=None, reference_name=None, note=None, billing_group=None
) -> dict:
	"""Book a credit entry for a partial-overcharge / gateway refund to wallet.

	`billing_group` returns the refund to that group's own budget rather than the
	general pool — pass the refunded invoice's `billing_group` so a refund on a
	group's invoice doesn't leak into money reserved for the team's consolidated
	invoice or another group.
	"""
	entry, new_balance = _book_entry(
		team,
		"Credit",
		amount,
		currency,
		reference_type,
		reference_name,
		note or "Refund to wallet",
		billing_group=billing_group,
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
	team: str,
	amount: float,
	entry_type: str,
	currency: str | None = None,
	note: str | None = None,
	billing_group: str | None = None,
) -> dict:
	"""Admin manual correction — a credit or debit entry with an audit note.

	`billing_group` moves the correction into (or out of) that group's own budget
	rather than the general pool — e.g. an operator re-earmarking a mistagged
	top-up.
	"""
	if entry_type not in ("Credit", "Debit"):
		frappe.throw(_("entry_type must be 'Credit' or 'Debit'."), frappe.ValidationError)
	entry, new_balance = _book_entry(
		team,
		entry_type,
		amount,
		currency,
		reference_type="Admin",
		note=note or "Admin adjustment",
		billing_group=billing_group,
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


def credit_lots(team: str, currency: str, billing_group: str | None = None) -> list[dict]:
	"""Every credit booking in one scope of this wallet, with how much of each is left.

	Derived by replaying the ledger: debits are drawn against credits in
	(expiry, then age) order, so a grant expiring on Friday is spent before one
	expiring next month, and both before credit that never expires.

	Scoped to `billing_group` (None = the general pool) — replaying the WHOLE
	wallet's entries as one FIFO queue, mixing tagged and untagged, would let a
	group's debit appear to consume a general-pool grant it never actually touched
	(`_post_entry` only ever lets a tagged Debit draw against that SAME tag's
	Credits). Each scope's remainders sum to that scope's own budget — `group_budget`
	or `general_pool_balance` — not the whole wallet balance.
	"""
	import datetime

	cle = frappe.qb.DocType("Credit Ledger Entry")
	scope = (
		cle.billing_group.isnull() | (cle.billing_group == "")
		if not billing_group
		else cle.billing_group == billing_group
	)
	rows = (
		frappe.qb.from_(cle)
		.select(cle.name, cle.entry_type, cle.amount, cle.expires_on, cle.creation)
		.where((cle.team == team) & (cle.currency == currency) & scope)
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


def expiring_credits(
	team: str, currency: str | None = None, on_date=None, billing_group: str | None = None
) -> list[dict]:
	"""Unspent promotional credit that still has an expiry date ahead of it.

	What the customer is shown as "expiring soon" — one row per grant, soonest first.
	Grants already past their date are not included: the sweep books them out, and
	until it runs they are not the customer's to spend anyway.
	"""
	currency = _resolve_currency(team, currency)
	on_date = frappe.utils.getdate(on_date)
	return [
		{"amount": lot.remaining, "expires_on": lot.expires_on, "ledger_entry": lot.name}
		for lot in credit_lots(team, currency, billing_group)
		if lot.expires_on and lot.remaining > 0 and frappe.utils.getdate(lot.expires_on) > on_date
	]


def expire_credits(team: str, currency: str, on_date=None, billing_group: str | None = None) -> list[dict]:
	"""Sweep every expired grant off one scope of one wallet; returns what was written off.

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
			return _expire_credits_once(team, currency, on_date, billing_group)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == _DEADLOCK_RETRIES - 1:
				raise
			_backoff(attempt)
	return []


def _expire_credits_once(team: str, currency: str, on_date, billing_group: str | None = None) -> list[dict]:
	"""One sweep attempt: lock the wallet, then write off what has run out of time."""
	_ensure_wallet(team, currency)
	balance = _lock_and_read_balance(team, currency)

	expired = []
	for lot in credit_lots(team, currency, billing_group):
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
			billing_group=billing_group,
		)
		expired.append({"ledger_entry": entry.name, "amount": lot.remaining, "expired_grant": lot.name})
	return expired


def run_credit_expiry(on_date=None) -> dict:
	"""Daily: write off promotional credit that has run out of time.

	Scans only (team, currency, billing_group) scopes that hold a grant already past
	its date — a team whose credit never expires is never looked at. Scoped by
	billing_group too, not just (team, currency): each scope's grants are swept
	independently, since `credit_lots` (and so `expire_credits`) only ever replays
	one scope's own entries.
	"""
	on_date = frappe.utils.getdate(on_date)
	cle = frappe.qb.DocType("Credit Ledger Entry")
	scopes = (
		frappe.qb.from_(cle)
		.select(cle.team, cle.currency, cle.billing_group)
		.distinct()
		.where((cle.entry_type == "Credit") & cle.expires_on.isnotnull() & (cle.expires_on <= on_date))
		.run(as_dict=True)
	)

	swept, total = 0, 0.0
	for scope in scopes:
		# A wallet with nothing in it has nothing to expire; skip before taking a lock.
		if (
			frappe.utils.flt(
				frappe.db.get_value("Credit Wallet", wallet_name(scope.team, scope.currency), "balance")
			)
			<= 0
		):
			continue
		for expiry in expire_credits(scope.team, scope.currency, on_date, scope.billing_group or None):
			swept += 1
			total += expiry["amount"]
			frappe.logger("billing").info(
				f"expired {expiry['amount']} {scope.currency} of promotional credit "
				f"for {scope.team} (grant {expiry['expired_grant']})"
				+ (f" [group {scope.billing_group}]" if scope.billing_group else "")
			)

	return {"wallets": len(scopes), "entries": swept, "amount": total}
