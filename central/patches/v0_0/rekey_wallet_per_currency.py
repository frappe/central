# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Re-key Credit Wallet from `team` to `(team, currency)` and forbid a negative
balance at the database (ADR 0018).

The wallet carried ONE currency-blind `balance` per team while the ledger carried
per-currency entries. The invoice waterfall read a per-currency balance
(`get_balance(team, currency)`, which summed the ledger) but debited the
currency-blind anchor — so the read and the write used different definitions of
"balance", and a team holding two currencies could be driven negative in one of
them while the anchor stayed positive. It was closed only by Billing Profile
locking a team to a single currency: an invariant living nowhere near the code
that depended on it.

This patch:

1.  Rebuilds the anchors as one row per (team, currency), named `{team}-{currency}`,
    with the balance recomputed from that currency's ledger entries.
2.  Rewrites `Credit Ledger Entry.running_balance` as a per-currency cumulative
    (it was a currency-blind one), so the anchor and the newest entry agree.
3.  Applies `CHECK (balance >= 0)` — the point of the exercise, since `frappe.db.
    set_value` skips the controller and so a Python guard protects only polite callers.

The constraint itself is declared in `billing/platform/constraints.py` and applied by
an `after_install` / `after_migrate` hook, NOT here. A constraint that lived only in a
patch would be absent on fresh sites (Frappe marks patches as executed without running
them on a new install). This patch just calls the same idempotent helper so a site
migrating through v27 gets it immediately rather than on its next migrate.

Idempotent: recomputes from the ledger each run.
"""

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum

from central.billing.platform.constraints import ensure_constraints


def execute():
	_backfill_missing_currency()
	_rebuild_anchors()
	_rewrite_running_balance()
	ensure_constraints()


def _team_currencies() -> dict[str, list[str]]:
	"""Every (team, currency) pair the ledger knows about — one query, no N+1."""
	cle = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(cle.entry_type == "Credit", cle.amount).else_(-cle.amount)
	rows = (
		frappe.qb.from_(cle)
		.select(cle.team, cle.currency, Sum(signed).as_("balance"))
		.groupby(cle.team, cle.currency)
		.run(as_dict=True)
	)
	pairs: dict[str, list[str]] = {}
	for r in rows:
		pairs.setdefault(r.team, []).append(r)
	return pairs


def _backfill_missing_currency():
	"""Ledger entries predating the currency column: stamp the team's billing currency.

	A NULL currency would otherwise group into its own phantom wallet and the Link
	field is now required.
	"""
	cle = frappe.qb.DocType("Credit Ledger Entry")
	orphans = (
		frappe.qb.from_(cle)
		.select(cle.name, cle.team)
		.where(cle.currency.isnull() | (cle.currency == ""))
		.run(as_dict=True)
	)
	if not orphans:
		return
	teams = list({o.team for o in orphans})
	profile = dict(
		frappe.get_all(
			"Billing Profile",
			filters={"team": ["in", teams]},
			fields=["team", "currency"],
			as_list=True,
		)
	)
	for o in orphans:
		frappe.db.set_value(
			"Credit Ledger Entry", o.name, "currency", profile.get(o.team) or "INR",
			update_modified=False,
		)


def _rebuild_anchors():
	"""One anchor per (team, currency), balance recomputed from that currency's ledger."""
	pairs = _team_currencies()

	# Wallets with no ledger history at all (a provisioned-but-unused wallet) keep a
	# zero-balance anchor in the team's billing currency so nothing 404s on read.
	for w in frappe.get_all("Credit Wallet", fields=["name", "team", "currency"]):
		if w.team not in pairs:
			currency = w.currency or frappe.db.get_value(
				"Billing Profile", w.team, "currency"
			) or "INR"
			pairs[w.team] = [frappe._dict({"team": w.team, "currency": currency, "balance": 0})]

	frappe.db.delete("Credit Wallet")  # names change; rebuild rather than rename

	for team, rows in pairs.items():
		if not frappe.db.exists("Team", team):
			continue  # a deleted team's ledger is history, not a live wallet
		for r in rows:
			frappe.get_doc(
				{
					"doctype": "Credit Wallet",
					"team": team,
					"currency": r["currency"],
					"balance": max(frappe.utils.flt(r["balance"]), 0.0),
				}
			).insert(ignore_permissions=True)


def _rewrite_running_balance():
	"""`running_balance` becomes a per-currency cumulative, matching the new anchor."""
	entries = frappe.get_all(
		"Credit Ledger Entry",
		fields=["name", "team", "currency", "entry_type", "amount"],
		order_by="team asc, currency asc, creation asc, name asc",
	)
	running: dict[tuple[str, str], float] = {}
	for e in entries:
		key = (e.team, e.currency)
		delta = frappe.utils.flt(e.amount) * (1 if e.entry_type == "Credit" else -1)
		running[key] = running.get(key, 0.0) + delta
		frappe.db.set_value(
			"Credit Ledger Entry", e.name, "running_balance", running[key],
			update_modified=False,
		)


