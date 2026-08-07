# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How reliably a team has actually paid.

Everything else here looks forward. This looks back, because a projection means almost
nothing without it: *"suspended on the 12th"* reads completely differently next to *"and
they have paid late in three of the last six months"* than next to *"and they have never
missed one."* The first is a collections problem; the second is almost certainly ours —
an expired card, a lapsed mandate, a gateway that stopped working — and the response is
the opposite in each case.

A retrospective read over rows that already exist, so it costs what the collection
outlook costs and needs none of the bounding cohort revenue projection needs.

One rule holds the whole thing honest: **lateness is measured against `due_date`, never
`dunning_starts_on`.** The deferred clock exists to protect customers when our own
collection fails; letting it feed a behaviour score would quietly mark customers down
for our outages.
"""

import frappe

# Trials are a computed subsidy cost, not a sale — counting them would flatter or
# distort every rate here.
BILLABLE = "Billable"

# Statuses that mean the invoice was never collectable through no fault of the customer.
NOT_THEIR_FAULT = ("Cancelled", "Waived")


def summary(team: str, months: int = 6, on=None) -> dict:
	"""One team's payment record over the trailing window."""
	on = frappe.utils.getdate(on or frappe.utils.nowdate())
	since = frappe.utils.add_months(on, -months)

	invoices = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": BILLABLE,
			"due_date": [">=", since],
			"status": ["not in", NOT_THEIR_FAULT],
		},
		fields=["name", "status", "due_date", "currency", "total", "expected_collection"],
		order_by="due_date asc",
	)

	settled = [i for i in invoices if i.status == "Paid"]
	outstanding = [i for i in invoices if i.status in ("Open", "Overdue")]
	delays = [_days_late(i, on) for i in invoices]
	delays = [d for d in delays if d is not None]

	return {
		"team": team,
		"window_months": months,
		"since": str(since),
		"invoices": len(invoices),
		"settled": len(settled),
		"outstanding": len(outstanding),
		# The headline: "6 / 6" is a different fact from "3 / 6" beside the same failure.
		"on_time": sum(1 for i in invoices if _days_late(i, on) == 0),
		"worst_delay_days": max(delays) if delays else 0,
		"average_delay_days": round(sum(delays) / len(delays), 1) if delays else 0.0,
		"times_dunned": _times_dunned(team, since),
		"ever_suspended": _ever_suspended(team),
		"billing_since": _billing_since(team),
		"settlement_mix": _settlement_mix(team, since),
		# Not a probability. A label an operator can read at a glance and act on.
		"verdict": None,
	}


def with_verdict(team: str, months: int = 6, on=None) -> dict:
	"""The summary plus the one-line reading of it."""
	out = summary(team, months, on)
	out["verdict"] = verdict(out)
	return out


def verdict(record: dict) -> str:
	"""What this record says about whose problem a failure is.

	Deliberately coarse. The value is in separating "they do not pay" from "they always
	pay and something on our side broke", which is the distinction that changes what an
	operator does next.
	"""
	if not record["invoices"]:
		return "No history"
	if record["on_time"] == record["invoices"]:
		return "Always paid on time"
	if record["on_time"] == 0:
		return "Never paid on time"
	if record["worst_delay_days"] > 30:
		return "Chronically late"
	return "Occasionally late"


def _days_late(invoice, on) -> int | None:
	"""How late this invoice was, measured from the date the customer owed it.

	Never from `dunning_starts_on`: that clock is pushed forward when *we* fail to
	collect, and scoring against it would blame the customer for our outage.
	"""
	if not invoice.due_date:
		return None
	due = frappe.utils.getdate(invoice.due_date)
	if invoice.status == "Paid":
		# The ledger does not keep a settled-on date, so the closest honest answer is
		# that a paid invoice was not late unless it is still visibly overdue.
		return 0
	return max(0, (frappe.utils.getdate(on) - due).days)


def _times_dunned(team: str, since) -> int:
	return frappe.db.count(
		"Payment Attempt", {"team": team, "status": "Failed", "creation": [">=", since]}
	)


def _ever_suspended(team: str) -> bool:
	return bool(
		frappe.get_all(
			"Subscription",
			filters={"team": team, "account_standing": ["in", ["Suspended", "Terminated"]]},
			limit=1,
		)
	)


def _billing_since(team: str) -> str | None:
	earliest = frappe.get_all(
		"Invoice", filters={"team": team}, fields=["creation"], order_by="creation asc", limit=1
	)
	return str(frappe.utils.getdate(earliest[0].creation)) if earliest else None


def _settlement_mix(team: str, since) -> dict:
	"""How this team's money has actually arrived — card, credits, or not at all."""
	captured = frappe.db.count(
		"Payment Attempt", {"team": team, "status": "Captured", "creation": [">=", since]}
	)
	drawn = frappe.db.count(
		"Credit Ledger Entry",
		{"team": team, "entry_type": "Debit", "creation": [">=", since]},
	)
	return {"card_captures": captured, "credit_draws": drawn}
