# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The single transition authority for billing state machines (ADR 0016).

Every billing status change goes through `transition()`: it validates the move against
the machine that owns that document's status, writes the field, and appends one
immutable `Billing Event`. Assigning a status field directly anywhere else in
`central/billing` is banned — a test greps the module for it, the same shape of guard
that keeps raw SQL out.

The Billing Event stream is **derived**: no pricing, invoicing, settlement, dunning or
entitlement code may read it. Drop the table and not one invoice total changes. This is
the load-bearing constraint that stops the stream becoming a second source of truth
(ADR 0010).
"""

import frappe
from frappe import _


class InvalidTransition(frappe.ValidationError):
	"""A status move the owning state machine forbids."""


class StateMachine:
	"""One document's status field and the legal moves between its states."""

	def __init__(self, doctype: str, field: str, edges: dict):
		self.doctype = doctype
		self.field = field
		self.edges = {frm: set(tos) for frm, tos in edges.items()}

	def allows(self, from_state, to_state) -> bool:
		return to_state in self.edges.get(from_state, set())

	def states(self) -> set:
		out = set(self.edges)
		for tos in self.edges.values():
			out |= tos
		return out


# --- The machines -------------------------------------------------------------
# One entry per billing state machine. Terminal states carry an empty edge set, so the
# machine — not the caller — refuses to pay a cancelled invoice or reopen a paid one.

INVOICE = StateMachine(
	"Invoice",
	"status",
	{
		"Draft": {"Open", "Paid", "Cancelled"},  # opened, or settled outright by credits
		"Open": {"Paid", "Overdue", "Cancelled", "Waived"},
		"Overdue": {"Paid", "Cancelled", "Waived"},
		"Paid": set(),  # terminal — corrections are cancel+reissue (pre-pay) or refund
		"Cancelled": set(),  # terminal
		"Waived": set(),  # terminal
	},
)

PAYMENT_ATTEMPT = StateMachine(
	"Payment Attempt",
	"status",
	{
		"Initiated": {"Authorised", "Captured", "Failed"},
		"Authorised": {"Captured", "Failed"},
		# A synced capture is not final until the webhook, and a failure webhook may still
		# land first; a full refund sends it onward. Same-state re-captures no-op above.
		"Captured": {"Failed", "Refunded"},
		"Failed": set(),  # terminal
		"Refunded": set(),  # terminal
	},
)

# Account standing carries a mandatory grace step: Current cannot jump straight to
# Suspended. Reactivation from either non-current state returns to Current.
SUBSCRIPTION_STANDING = StateMachine(
	"Subscription",
	"account_standing",
	{
		"Current": {"Past Due"},
		"Past Due": {"Current", "Suspended"},
		"Suspended": {"Current"},
	},
)

REFUND = StateMachine(
	"Refund",
	"status",
	{
		"Initiated": {"Completed", "Failed"},
		"Completed": set(),  # terminal
		"Failed": set(),  # terminal
	},
)

PAYMENT_METHOD = StateMachine(
	"Payment Method",
	"status",
	{
		"Pending Validation": {"Active", "Failed"},
		"Active": {"Paused", "Cancelled", "Expired", "Failed"},
		"Paused": {"Active", "Cancelled", "Expired"},
		"Failed": set(),  # terminal — a fresh attempt is a new method
		"Cancelled": set(),  # terminal
		"Expired": set(),  # terminal
	},
)

# Inbound gateway webhook processing. No team and no money of its own, but routed
# through the authority so "why was this webhook ignored" is one query, and so the
# single owner rule holds uniformly (the grep guard has no special cases).
WEBHOOK_EVENT = StateMachine(
	"Webhook Event",
	"status",
	{
		"Received": {"Processed", "Failed", "Ignored"},
		"Failed": {"Processed", "Ignored"},  # a retried webhook can still land
		"Processed": set(),
		"Ignored": set(),
	},
)

# The monthly run's own progress. No money of its own, but routed through the
# authority so the single owner rule holds with no special cases.
BILLING_RUN = StateMachine(
	"Billing Run",
	"status",
	{
		# Straight to Complete is legal: a month where no team had anything billable is
		# finished without ever having something to collect.
		"Drafting": {"Collecting", "Complete"},
		"Collecting": {"Complete"},
		"Complete": {"Collecting"},  # a late draft reopens collection for the period
	},
)

# One bulk re-issue of a period's invoices.
RERATING_RUN = StateMachine(
	"Rerating Run",
	"status",
	{
		"Running": {"Complete", "Failed"},
		"Complete": set(),  # terminal — a further correction is a new run
		"Failed": set(),  # terminal
	},
)

COMMITMENT = StateMachine(
	"Commitment",
	"status",
	{
		"Active": {"Completed", "Breached"},
		"Completed": set(),  # terminal — the term ran and was honoured
		"Breached": set(),  # terminal — a period fell short; later periods get no discount
	},
)

_MACHINES = {
	m.doctype: m
	for m in (
		INVOICE,
		PAYMENT_ATTEMPT,
		SUBSCRIPTION_STANDING,
		REFUND,
		PAYMENT_METHOD,
		WEBHOOK_EVENT,
		BILLING_RUN,
		RERATING_RUN,
		COMMITMENT,
	)
}


def machine_for(doctype: str) -> StateMachine:
	machine = _MACHINES.get(doctype)
	if not machine:
		frappe.throw(_("No billing state machine owns {0}.").format(doctype), InvalidTransition)
	return machine


def transition(
	doc,
	to_state: str,
	reason: str | None = None,
	actor: str | None = None,
	correlation: str | None = None,
	amount=None,
	event_type: str | None = None,
) -> None:
	"""Move `doc` to `to_state` through its machine, and append a Billing Event.

	Validates the edge (raising `InvalidTransition` on an illegal move), writes the
	status field on the in-memory doc, and records the move on the derived stream. It
	does **not** save the doc: a caller usually sets other fields in the same save, and
	the event insert rides the same transaction, so both commit or roll back together.

	`correlation` threads everything triggered by settling one invoice onto that
	invoice's name; it defaults to the doc's own name, which is right for an invoice's
	own transitions and is what a caller acting on a related doc (an attempt, a refund)
	overrides.
	"""
	machine = machine_for(doc.doctype)
	from_state = doc.get(machine.field)
	if from_state == to_state:
		# Idempotent no-op. A duplicate/late webhook, a reconciliation replay, or dunning
		# re-applying a standing all re-drive the SAME outcome; that is not an illegal move
		# and must not raise (or append a second event) — it simply already happened.
		return
	if not machine.allows(from_state, to_state):
		frappe.throw(
			_("{0} {1}: illegal transition {2} → {3}.").format(doc.doctype, doc.name, from_state, to_state),
			InvalidTransition,
		)
	doc.set(machine.field, to_state)
	_append_event(doc, from_state, to_state, reason, actor, correlation, amount, event_type)


def _append_event(doc, from_state, to_state, reason, actor, correlation, amount, event_type) -> None:
	frappe.get_doc(
		{
			"doctype": "Billing Event",
			"team": doc.get("team"),
			"occurred_at": frappe.utils.now_datetime(),
			"event_type": event_type or f"{doc.doctype} {to_state}",
			"subject_doctype": doc.doctype,
			"subject": doc.name,
			"from_state": from_state,
			"to_state": to_state,
			"amount": amount,
			"currency": doc.get("currency"),
			"actor": actor or _default_actor(),
			"reason": reason,
			"correlation": correlation or doc.name,
		}
	).insert(ignore_permissions=True)


def _default_actor() -> str:
	"""Who is making the move when a caller does not say — the session user, or the
	scheduler/worker running headless."""
	user = getattr(frappe.session, "user", None)
	return user or "system"
