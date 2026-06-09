# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Subscription intent + the two-axis state model (issue #04).

A Central Subscription is the customer's *intent/contract*, not billing truth —
the authoritative runtime record is born at the cluster and reported by the
Agent (#03). State lives on two orthogonal axes, never one enum:

  - operational (running / stopped / terminated) — owned by the Agent
  - account standing (current / past_due / suspended) — owned by Central, here

Central never stores the operational axis: a resource can be `running` and
`past_due` at once (normal grace), so collapsing them would lose information.
Every transition writes an append-only Subscription Change.
"""

import frappe


class InvalidTransition(frappe.ValidationError):
	"""An account-standing transition that the state machine does not permit."""


# Account-standing transitions Central allows. Suspension is staged through
# past_due (grace) — never a direct current -> suspended jump; reactivation
# returns to current from either past_due or suspended.
_STANDING_TRANSITIONS = {
	"current": {"past_due"},
	"past_due": {"current", "suspended"},
	"suspended": {"current"},
}

# The Subscription Change type that records a move *into* a standing.
_STANDING_CHANGE_TYPE = {
	"past_due": "past_due",
	"suspended": "suspended",
	"current": "reactivated",
}


def _record_change(subscription: str, change_type: str, old_value=None, new_value=None, changed_by=None):
	"""Append one immutable Subscription Change row."""
	return frappe.get_doc(
		{
			"doctype": "Subscription Change",
			"subscription": subscription,
			"change_type": change_type,
			"old_value": old_value,
			"new_value": new_value,
			"effective_at": frappe.utils.now_datetime(),
			"changed_by": changed_by or frappe.session.user,
		}
	).insert(ignore_permissions=True)


def create_subscription(
	team: str,
	cluster: str,
	plan: str,
	billing_cycle: str = "monthly",
	start_date=None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Record a subscription INTENT. Provisioning happens at the cluster; the
	authoritative event (resource_id, shown_rate) is born there and reported by
	the Agent. This only captures what the customer asked for."""
	doc = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"cluster": cluster,
			"plan": plan,
			"billing_cycle": billing_cycle,
			"account_standing": "current",
			"start_date": start_date or frappe.utils.nowdate(),
			"default_payment_method": default_payment_method,
			"gateway": gateway,
		}
	).insert(ignore_permissions=True)

	_record_change(doc.name, "created", new_value=plan, changed_by=changed_by)
	return doc


def change_plan(subscription: str, new_plan: str, changed_by: str | None = None):
	"""Change the requested plan (intent). A new price-lock is created at the
	cluster on reprovision (#03) — this records the contract change only."""
	doc = frappe.get_doc("Subscription", subscription)
	old_plan = doc.plan
	if new_plan == old_plan:
		return doc
	doc.plan = new_plan
	doc.save(ignore_permissions=True)
	_record_change(subscription, "plan_changed", old_plan, new_plan, changed_by)
	return doc


def change_payment_method(subscription: str, new_method: str, changed_by: str | None = None):
	doc = frappe.get_doc("Subscription", subscription)
	old_method = doc.default_payment_method
	doc.default_payment_method = new_method
	doc.save(ignore_permissions=True)
	_record_change(subscription, "payment_method_changed", old_method, new_method, changed_by)
	return doc


def cancel_subscription(subscription: str, changed_by: str | None = None):
	"""Cancel the subscription intent. The contract record is kept; the
	cancellation is logged. Stopping/terminating running resources is a separate
	operational concern owned by the Agent."""
	_record_change(subscription, "cancelled", changed_by=changed_by)
	return frappe.get_doc("Subscription", subscription)


def set_standing(subscription: str, new_standing: str, changed_by: str | None = None, reason=None):
	"""Move a subscription's account standing through the allowed transitions.

	Raises InvalidTransition for any move the state machine forbids (same-state,
	skipping the grace step, unknown standing). Records the move as an
	append-only Subscription Change. Never touches operational state.
	"""
	doc = frappe.get_doc("Subscription", subscription)
	current = doc.account_standing

	if new_standing not in _STANDING_TRANSITIONS.get(current, set()):
		raise InvalidTransition(
			f"Cannot move account standing from '{current}' to '{new_standing}'."
		)

	doc.account_standing = new_standing
	doc.save(ignore_permissions=True)
	_record_change(
		subscription,
		_STANDING_CHANGE_TYPE[new_standing],
		old_value=current,
		new_value=new_standing,
		changed_by=changed_by,
	)
	return doc


def reconcile_with_agent_event(subscription: str, resource_id: str) -> dict:
	"""Reconcile a subscription's intent against the authoritative cluster event.

	The real subscription event is born at the cluster; Central holds the price
	lock keyed by `resource_id` (#03). This compares the intended plan with the
	plan actually locked: a missing lock means the cluster has not yet reported
	(intent outstanding); a plan mismatch is surfaced for follow-up.
	"""
	from central.billing.revenue.pricelock import _open_lock

	doc = frappe.get_doc("Subscription", subscription)
	lock_name = _open_lock(resource_id)
	if not lock_name:
		return {"reconciled": False, "reason": "no_cluster_event", "intent_plan": doc.plan}

	locked_plan = frappe.db.get_value("Price Lock", lock_name, "plan")
	return {
		"reconciled": locked_plan == doc.plan,
		"intent_plan": doc.plan,
		"locked_plan": locked_plan,
		"resource_id": resource_id,
	}
