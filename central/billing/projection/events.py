# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Things that have not happened, placed on the calendar and rated as if they had.

Overrides change the rules; events change what happens. A resize on the 12th, a top-up
on the 20th, a card that declines on the second attempt — these are the questions an
operator asks when the answer to "what will this team be billed" is not the one they
were worried about.

The design constraint is the same as everywhere else here: an invented resize must be
rated by *exactly* the code that rates a real one, or the simulator becomes a second
model of billing and starts lying. So an injected event is not priced separately — it is
merged into the Subscription Change stream the line engine already reads, which means it
picks up day-weighting, the sub-24h churn window and the locked-rate segment boundaries
for free, because it is the same code path.

What an event cannot do is bypass a gate. A projected provision that would breach the
team's effective spend cap is reported as refused, with the reason, rather than quietly
billed — a scenario that could not happen is a finding, not a projection.
"""

import frappe

from central.billing.projection.basis import ASSUMED

RESIZE = "Resize"
PROVISION = "Provision"
CANCEL = "Cancel"
TOP_UP = "Top up"
DECLINE = "Decline"

SEGMENT_EVENTS = (RESIZE, PROVISION, CANCEL)


def merged_changes(events: list, period_start, period_end):
	"""A change source for the line engine: the real rows plus the invented ones.

	Returned as a callable so the engine asks for it at the moment it would have queried,
	and only for the subscriptions it is actually billing.
	"""
	from central.billing.revenue.invoicing.lines import _changes_by_subscription

	segment_events = [e for e in (events or []) if e.get("event_type") in SEGMENT_EVENTS]
	if not segment_events:
		return None

	def source(subscription_names):
		by_sub = _changes_by_subscription(subscription_names)
		for event in segment_events:
			subscription = event.get("subscription")
			if subscription not in subscription_names:
				continue
			rows = by_sub.setdefault(subscription, [])
			rows.append(_as_change(event))
		for subscription, rows in by_sub.items():
			# The segment builder depends on this order — a Cancelled sorted ahead of the
			# Created it closes would silently drop the segment.
			by_sub[subscription] = sorted(
				rows, key=lambda r: (frappe.utils.get_datetime(r.effective_at), r.get("creation") or "")
			)
		return by_sub

	return source


def _as_change(event) -> frappe._dict:
	"""One invented event, shaped exactly like the row the ledger would have written."""
	kind = event["event_type"]
	return frappe._dict(
		subscription=event.get("subscription"),
		change_type={RESIZE: "Plan Changed", PROVISION: "Created", CANCEL: "Cancelled"}[kind],
		new_value=event.get("plan"),
		# A cancellation closes the previous segment and carries no rate of its own.
		locked_rate=None if kind == CANCEL else frappe.utils.flt(event.get("rate")),
		effective_at=frappe.utils.get_datetime(event["on_date"]),
		creation=frappe.utils.get_datetime(event["on_date"]),
		injected=True,
	)


def mark_assumed(lines: list, events: list, period_start) -> list:
	"""Stamp lines that only exist because somebody invented an event.

	A line arising from a hypothetical is not a measurement and must not read as one, so
	it carries the same `assumed` basis a declared quantity does.
	"""
	dates = sorted(
		frappe.utils.get_datetime(e["on_date"])
		for e in (events or [])
		if e.get("event_type") in SEGMENT_EVENTS
	)
	if not dates:
		return lines

	earliest = min(dates)
	for line in lines:
		locked_at = (line.get("derivation") or {}).get("rate_locked_at")
		if locked_at and frappe.utils.get_datetime(locked_at) >= earliest:
			line["basis"] = ASSUMED
	return lines


def top_ups(events: list) -> list[dict]:
	"""Wallet credits an operator has invented, oldest first."""
	return sorted(
		(
			{
				"on_date": frappe.utils.getdate(e["on_date"]),
				"amount": frappe.utils.flt(e.get("amount")),
				"currency": e.get("currency"),
			}
			for e in (events or [])
			if e.get("event_type") == TOP_UP and frappe.utils.flt(e.get("amount"))
		),
		key=lambda t: t["on_date"],
	)


def declines(events: list) -> list[dict]:
	"""Charge attempts an operator has decided will fail."""
	return [
		{"on_date": frappe.utils.getdate(e["on_date"]), "attempt": frappe.utils.cint(e.get("attempt")) or 1}
		for e in (events or [])
		if e.get("event_type") == DECLINE
	]


def apply_declines(calendar: dict, team: str, events: list) -> dict:
	"""Walk the retry ladder spending the team's payment methods as declines burn them.

	A decline does **not** move any date, and it is worth being exact about that: the
	ladder is counted from the invoice's clock, and only *our* failure to collect ever
	pushes it (`defer_dunning`). A customer's card being refused is not our failure. What
	it changes is which method the next attempt reaches for — the charge loop escalates
	rather than repeating, so each decline burns one method — and what happens once there
	are none left.

	So the dates stay put and each retry gains two facts: the method it would try, and
	whether anything remains to try at all.
	"""
	assumed = {d["attempt"] for d in declines(events)}
	if not assumed:
		return calendar

	from central.billing.payments import collection

	methods = [m.name for m in collection.ordered_methods(team)]
	burnt: list[str] = []

	for stage in calendar.get("if_never_paid", []):
		if stage.get("stage") != "Retry":
			continue
		attempt = stage.get("attempt")
		available = [m for m in methods if m not in burnt]
		stage["method"] = available[0] if available else None
		if not available:
			stage["note"] = "Nothing left to try — every method has been refused."
		elif attempt in assumed:
			stage["assumed_declined"] = True
			stage["note"] = "Assumed refused; the next attempt escalates to another method."
			burnt.append(available[0])
		else:
			stage["note"] = "Charges the next untried method."

	calendar["methods_exhausted"] = len(burnt) >= len(methods) and bool(methods)
	return calendar


def refusals(team: str, events: list, state=None) -> list[dict]:
	"""Injected provisions the real gates would not have allowed.

	Checked against the same helpers provisioning checks against, so a scenario cannot
	quietly assume a resource the platform would have refused to create.
	"""
	from central.billing.payments import settlement

	planned = [e for e in (events or []) if e.get("event_type") in (PROVISION, RESIZE) and e.get("rate")]
	if not planned:
		return []

	out = []
	for event in planned:
		rate = frappe.utils.flt(event["rate"])
		if not settlement.can_accept_spend(team, rate, source=state):
			cap = settlement.effective_spend_cap(team, source=state)
			out.append(
				{
					"event": event.get("event_type"),
					"on_date": str(frappe.utils.getdate(event["on_date"])),
					"reason": "Over the effective spend cap",
					"detail": (
						f"{rate:,.2f} against a cap of {frappe.utils.flt(cap):,.2f}. "
						"The platform would refuse to provision this."
					),
				}
			)
	return out


def timeline(events: list) -> list[dict]:
	"""The injected events as dated rows, marked so nobody reads them as history."""
	return [
		{
			"date": str(frappe.utils.getdate(e["on_date"])),
			"event": e.get("event_type"),
			"detail": _describe(e),
			"hypothetical": True,
		}
		for e in sorted(events or [], key=lambda e: frappe.utils.getdate(e["on_date"]))
	]


def _describe(event) -> str:
	kind = event.get("event_type")
	if kind in (RESIZE, PROVISION):
		return f"{event.get('plan') or 'config'} at {frappe.utils.flt(event.get('rate')):,.2f}"
	if kind == TOP_UP:
		return f"{frappe.utils.flt(event.get('amount')):,.2f} added to the wallet"
	if kind == DECLINE:
		return f"attempt {frappe.utils.cint(event.get('attempt')) or 1} fails"
	return ""
