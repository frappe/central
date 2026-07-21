# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rung 4 of the enforcement ladder — the invariants no constraint can hold (ADR 0018).

An invariant belongs here ONLY if it cannot be pushed lower. `balance >= 0` is a
`CHECK` constraint (rung 1) and has no business being audited. But
`wallet.balance == Σ(ledger)` spans two tables, and no `CHECK` can see both — so it is
audited, and audit is the *weakest* rung: it detects, it does not prevent.

Every check answers one question with a second, independent derivation of a number the
system already believes. Where the two disagree, money has drifted. That is a defect
with a team and an amount attached, not a metric.

`observability.md` §6 asked for these as counters. A counter has no teeth, which is
why it was specified and never built. These return violations — rows a human reads,
surfaced by the **Billing Invariant Violations** report and a daily job that only
speaks up when something is wrong.

**Adding a check:** write a function returning `list[Violation]`, register it in
`CHECKS`. Aggregate in SQL; never loop a query per row — this runs over the whole
ledger.
"""

from dataclasses import asdict, dataclass

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Count, Sum

# Money is float `Currency` in major units, so an exact `==` is a bug. Anything at or
# under a minor unit is rounding, not drift; anything above it is real.
TOLERANCE = 0.01

# Payment Attempts are pruned on a rolling window (charges.cleanup_payment_logs), so an
# invoice older than the window has no attempts to reconcile against and would report a
# false violation. Audits that read attempts stay inside the window.
from central.billing.payments.charges import LOG_RETENTION_DEFAULT_DAYS

STUCK_ATTEMPT_MINUTES = 30

# Attempt statuses that mean money actually moved. `Refunded` belongs here: it is a
# CAPTURED attempt that was later reversed, and the reversal does not un-pay the
# invoice (refunds go to source or to the wallet; the invoice stays Paid).
TOOK_MONEY = ("Captured", "Refunded")

# Non-terminal: the gateway's answer is not yet known. Anything here past the threshold
# is a question the system has failed to answer (ADR 0017).
IN_FLIGHT = ("Initiated", "Authorised")


@dataclass
class Violation:
	check: str
	detail: str
	team: str | None = None
	currency: str | None = None
	subject_doctype: str | None = None
	subject: str | None = None
	expected: float | None = None
	actual: float | None = None

	@property
	def drift(self) -> float:
		if self.expected is None or self.actual is None:
			return 0.0
		return frappe.utils.flt(self.actual - self.expected, 2)


def _differs(a, b) -> bool:
	return abs(frappe.utils.flt(a) - frappe.utils.flt(b)) > TOLERANCE


def _attempt_cutoff():
	days = int(frappe.conf.get("payment_log_retention_days") or LOG_RETENTION_DEFAULT_DAYS)
	return frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-days)


# --- C2: the wallet anchor agrees with the ledger ----------------------------


def check_wallet_matches_ledger() -> list[Violation]:
	"""`Credit Wallet.balance` == Σ signed `Credit Ledger Entry`, per (team, currency).

	The canary for the anchor/ledger split. The anchor is the authoritative balance
	(maintained under its row lock) and the ledger is the audit trail; if they part
	company, one of them is lying about a customer's money.
	"""
	cle = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(cle.entry_type == "Credit", cle.amount).else_(-cle.amount)
	ledger = {
		(r.team, r.currency): frappe.utils.flt(r.balance)
		for r in frappe.qb.from_(cle)
		.select(cle.team, cle.currency, Sum(signed).as_("balance"))
		.groupby(cle.team, cle.currency)
		.run(as_dict=True)
	}

	violations = []
	seen = set()
	for w in frappe.get_all(
		"Credit Wallet", fields=["name", "team", "currency", "balance"]
	):
		key = (w.team, w.currency)
		seen.add(key)
		expected = ledger.get(key, 0.0)
		if _differs(w.balance, expected):
			violations.append(
				Violation(
					check="C2",
					team=w.team,
					currency=w.currency,
					subject_doctype="Credit Wallet",
					subject=w.name,
					expected=expected,
					actual=frappe.utils.flt(w.balance),
					detail="Wallet balance does not equal the signed sum of its ledger.",
				)
			)

	# Ledger entries with no anchor at all: the balance is unreachable by the booking
	# path, so the customer's credits are invisible to settlement.
	for key, balance in ledger.items():
		if key not in seen and abs(balance) > TOLERANCE:
			team, currency = key
			violations.append(
				Violation(
					check="C2",
					team=team,
					currency=currency,
					subject_doctype="Credit Ledger Entry",
					expected=balance,
					actual=0.0,
					detail="Ledger entries exist for this currency with no Credit Wallet anchor.",
				)
			)
	return violations


# --- C4: the running_balance chain is unbroken -------------------------------


def check_running_balance_chain() -> list[Violation]:
	"""Each entry's `running_balance` == the previous one ± its own signed amount.

	This is what makes the ledger *self-verifying*: a deleted, reordered or tampered
	entry breaks the chain even if the final balance happens to add up. Reports only
	the FIRST break per (team, currency) — everything after it is the same defect.
	"""
	entries = frappe.get_all(
		"Credit Ledger Entry",
		fields=["name", "team", "currency", "entry_type", "amount", "running_balance"],
		order_by="team asc, currency asc, creation asc, name asc",
	)

	violations = []
	running: dict[tuple, float] = {}
	broken: set[tuple] = set()
	for e in entries:
		key = (e.team, e.currency)
		if key in broken:
			continue
		delta = frappe.utils.flt(e.amount) * (1 if e.entry_type == "Credit" else -1)
		running[key] = running.get(key, 0.0) + delta
		if _differs(e.running_balance, running[key]):
			broken.add(key)
			violations.append(
				Violation(
					check="C4",
					team=e.team,
					currency=e.currency,
					subject_doctype="Credit Ledger Entry",
					subject=e.name,
					expected=running[key],
					actual=frappe.utils.flt(e.running_balance),
					detail="running_balance chain breaks here — an entry is missing, "
					"reordered or altered.",
				)
			)
	return violations


# --- I1: the line items add up to the subtotal -------------------------------


def check_invoice_line_sum() -> list[Violation]:
	"""Σ(line items) == `Invoice.subtotal`. Should be impossible; >0 is an assembly bug."""
	item = frappe.qb.DocType("Invoice Line Item")
	lines = {
		r.parent: frappe.utils.flt(r.total)
		for r in frappe.qb.from_(item)
		.select(item.parent, Sum(item.amount).as_("total"))
		.groupby(item.parent)
		.run(as_dict=True)
	}

	violations = []
	for inv in frappe.get_all(
		"Invoice",
		filters={"status": ["!=", "Cancelled"]},
		fields=["name", "team", "currency", "subtotal"],
	):
		expected = lines.get(inv.name, 0.0)
		if _differs(inv.subtotal, expected):
			violations.append(
				Violation(
					check="I1",
					team=inv.team,
					currency=inv.currency,
					subject_doctype="Invoice",
					subject=inv.name,
					expected=expected,
					actual=frappe.utils.flt(inv.subtotal),
					detail="Invoice subtotal does not equal the sum of its line items.",
				)
			)
	return violations


# --- I5: a Paid invoice is actually covered ----------------------------------


def check_paid_invoice_is_covered() -> list[Violation]:
	"""A `Paid` invoice was covered: `amount_paid` + `credit_applied` >= `total` − TDS.

	Covers both settlement routes: the card path stamps `amount_paid`, the
	credits-cover-it-in-full path leaves it at zero and stamps `credit_applied`. An
	invoice marked Paid that neither covers is revenue we believe we collected and
	did not.
	"""
	violations = []
	for inv in frappe.get_all(
		"Invoice",
		filters={"status": "Paid", "invoice_type": ["!=", "Cost Report"]},
		fields=["name", "team", "currency", "total", "tds_amount", "amount_paid",
				"credit_applied"],
	):
		owed = frappe.utils.flt(inv.total) - frappe.utils.flt(inv.tds_amount)
		settled = frappe.utils.flt(inv.amount_paid) + frappe.utils.flt(inv.credit_applied)
		if settled + TOLERANCE < owed:
			violations.append(
				Violation(
					check="I5",
					team=inv.team,
					currency=inv.currency,
					subject_doctype="Invoice",
					subject=inv.name,
					expected=owed,
					actual=settled,
					detail="Invoice is Paid but card + credits do not cover what was owed.",
				)
			)
	return violations


# --- I6: one live invoice per (team, billing group, period) ------------------


def check_one_live_invoice_per_period() -> list[Violation]:
	"""A team is billed at most once for a period, per billing scope.

	The scope — the team's consolidated set of ungrouped assets, or one of its Billing
	Groups — is part of the grain. A team with groups legitimately holds several live
	invoices for one period; what it may never hold is two for the *same* scope.

	The unique index on `period_key` makes this impossible going forward; the audit
	is what surfaces the duplicates that predate it (the v28 patch flags them rather
	than cancelling them, because a *paid* duplicate is real money and needs a human).
	"""
	inv = frappe.qb.DocType("Invoice")
	rows = (
		frappe.qb.from_(inv)
		.select(
			inv.team,
			inv.billing_group,
			inv.period_start,
			inv.period_end,
			Count("*").as_("bills"),
		)
		.where(inv.status != "Cancelled")
		.groupby(inv.team, inv.billing_group, inv.period_start, inv.period_end)
		.having(Count("*") > 1)
		.run(as_dict=True)
	)
	return [
		Violation(
			check="I6",
			team=r.team,
			subject_doctype="Invoice",
			expected=1,
			actual=r.bills,
			detail=f"Team billed {r.bills}x for {r.period_start} – {r.period_end} "
			f"({'billing group ' + r.billing_group if r.billing_group else 'consolidated'}). "
			"If any duplicate was paid it needs a refund, not a cancellation.",
		)
		for r in rows
	]


# --- P2: captured payments equal what the invoice says was paid --------------


def check_captured_matches_amount_paid() -> list[Violation]:
	"""`Invoice.amount_paid` <= Σ(attempts that took money). Never more than was captured.

	This is an **inequality, and deliberately so.** Equality is not assertable today,
	because `amount_paid` has no defined meaning after a refund. Both of these are real,
	from live data:

	  - a fully-refunded invoice stays `Paid` with `amount_paid` intact (a dispute
	    refunds to source; the invoice is not un-billed) — so subtracting refunds from
	    the captured sum would flag a perfectly healthy invoice;
	  - a charge → refund → re-charge history has TWO money-taking attempts for one
	    invoice — so requiring the sum to *equal* `amount_paid` would flag that one.

	Any equality would therefore cry wolf on real histories, and a check that cries wolf
	is worse than no check (see `observability.md` §6, which specified equalities and was
	never built). What IS sound: we cannot have paid out more than the gateway ever took
	in. That catches the defect worth catching — an invoice marked `Paid` with nothing
	behind it — and stays silent on legitimate refund histories.

	Pinning `amount_paid`'s post-refund semantics is an open design question; when it is
	settled this check can be tightened to an equality.

	Scoped to the retention window because `cleanup_payment_logs` prunes terminal
	attempts after ~90 days — outside it there is nothing left to reconcile against.
	"""
	cutoff = _attempt_cutoff()
	pa = frappe.qb.DocType("Payment Attempt")
	captured = {
		r.invoice: frappe.utils.flt(r.total)
		for r in frappe.qb.from_(pa)
		.select(pa.invoice, Sum(pa.amount).as_("total"))
		.where(pa.status.isin(TOOK_MONEY) & pa.invoice.notnull())
		.groupby(pa.invoice)
		.run(as_dict=True)
	}

	violations = []
	for inv in frappe.get_all(
		"Invoice",
		filters={"status": "Paid", "creation": [">=", cutoff]},
		fields=["name", "team", "currency", "amount_paid"],
	):
		took = captured.get(inv.name, 0.0)
		if frappe.utils.flt(inv.amount_paid) > took + TOLERANCE:
			violations.append(
				Violation(
					check="P2",
					team=inv.team,
					currency=inv.currency,
					subject_doctype="Invoice",
					subject=inv.name,
					expected=took,
					actual=frappe.utils.flt(inv.amount_paid),
					detail="Invoice is Paid for more than the gateway ever captured — "
					"revenue we believe we collected with no payment behind it.",
				)
			)
	return violations


# --- P4: no intent is left non-terminal --------------------------------------


def check_no_stuck_attempts() -> list[Violation]:
	"""No Payment Attempt sits non-terminal past the threshold.

	An `Initiated` attempt is a charge whose outcome we do not know. Not knowing is a
	defect, not a resting state ([ADR 0017]): reconciliation must drive every one of
	them to terminal by asking the gateway. One that is still sitting here is one the
	sweeper has not answered — and possibly money taken with no settled record.
	"""
	stale = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), minutes=-STUCK_ATTEMPT_MINUTES
	)
	return [
		Violation(
			check="P4",
			team=a.team,
			currency=a.currency,
			subject_doctype="Payment Attempt",
			subject=a.name,
			actual=frappe.utils.flt(a.amount),
			detail=f"Attempt still '{a.status}' after {STUCK_ATTEMPT_MINUTES} minutes — "
			"its outcome at the gateway is unknown and unreconciled.",
		)
		for a in frappe.get_all(
			"Payment Attempt",
			filters={"status": ["in", IN_FLIGHT], "initiated_at": ["<", stale]},
			fields=["name", "team", "currency", "amount", "status"],
		)
	]


CHECKS = {
	"C2": ("Wallet balance equals its ledger", check_wallet_matches_ledger),
	"C4": ("Ledger running_balance chain is unbroken", check_running_balance_chain),
	"I1": ("Invoice subtotal equals its line items", check_invoice_line_sum),
	"I5": ("Paid invoice is covered by card + credits", check_paid_invoice_is_covered),
	"I6": ("One live invoice per team per period", check_one_live_invoice_per_period),
	"P2": ("Paid invoice never exceeds what was captured", check_captured_matches_amount_paid),
	"P4": ("No payment attempt left non-terminal", check_no_stuck_attempts),
}


def audit(only: str | None = None) -> list[Violation]:
	"""Run every registered check (or one) and return the violations, worst drift first."""
	keys = [only] if only else list(CHECKS)
	found: list[Violation] = []
	for key in keys:
		_title, fn = CHECKS[key]
		try:
			found.extend(fn())
		except Exception:
			# One broken check must not blind the other six.
			frappe.log_error(
				title=f"Billing invariant check {key} failed",
				message=frappe.get_traceback(),
			)
	found.sort(key=lambda v: abs(v.drift), reverse=True)
	return found


def run_invariant_audit() -> dict:
	"""Daily: assert the money invariants and speak up only when one is broken.

	Silence is the success case. A violation is logged with its team and amount so it
	is actionable without opening a dashboard.
	"""
	violations = audit()
	if not violations:
		frappe.logger("billing").info("invariant audit clean")
		return {"violations": 0, "by_check": {}}

	by_check: dict[str, int] = {}
	for v in violations:
		by_check[v.check] = by_check.get(v.check, 0) + 1
		frappe.logger("billing").error(
			f"INVARIANT {v.check} violated — team={v.team} {v.subject_doctype}={v.subject} "
			f"expected={v.expected} actual={v.actual}: {v.detail}"
		)
	frappe.log_error(
		title=f"Billing invariant audit: {len(violations)} violation(s)",
		message=frappe.as_json([asdict(v) for v in violations[:50]], indent=2),
	)
	return {"violations": len(violations), "by_check": by_check}
