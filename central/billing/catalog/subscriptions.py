# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Subscription intent + the two-axis state model (issue #04).

A Central Subscription is the customer's *intent/contract*. Agentless (ADR 0006):
Central provisions via the cluster manager and writes the authoritative runtime
record (the price-lock) itself, at provision time — see `provision_subscription`.
State lives on two orthogonal axes, never one enum:

  - operational (running / stopped / terminated) — Central's record of cluster-
    manager state (read from / reported by the cluster manager)
  - account standing (current / past_due / suspended) — owned by Central, here

Central never collapses the axes: a resource can be `running` and `past_due` at
once (normal grace), so one enum would lose information. Every standing transition
writes an append-only Subscription Change.
"""

import frappe


class InvalidTransition(frappe.ValidationError):
	"""An account-standing transition that the state machine does not permit."""


# Account-standing transitions Central allows. Suspension is staged through
# past_due (grace) — never a direct current -> suspended jump; reactivation
# returns to current from either past_due or suspended.
_STANDING_TRANSITIONS = {
	"Current": {"Past Due"},
	"Past Due": {"Current", "Suspended"},
	"Suspended": {"Current"},
}

# The Subscription Change type that records a move *into* a standing.
_STANDING_CHANGE_TYPE = {
	"Past Due": "Past Due",
	"Suspended": "Suspended",
	"Current": "Reactivated",
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
	billing_cycle: str = "Monthly",
	start_date=None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Record a subscription INTENT — what the customer asked for. The actual
	provisioning (calling the cluster manager and writing the price-lock) is
	`provision_subscription`; this captures the contract only, so it stays usable
	for fixtures and intent-only flows."""
	doc = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"cluster": cluster,
			"plan": plan,
			"billing_cycle": billing_cycle,
			"account_standing": "Current",
			"start_date": start_date or frappe.utils.nowdate(),
			"default_payment_method": default_payment_method,
			"gateway": gateway,
		}
	)
	doc.flags.changed_by = changed_by
	doc.insert(ignore_permissions=True)

	return doc


def provision_subscription(
	team: str,
	cluster: str,
	plan: str,
	billing_cycle: str = "Monthly",
	start_date=None,
	resource_id: str | None = None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Provision a subscription the agentless way (ADR 0006): record the intent,
	then — as the *same* component — write the authoritative runtime record.

	Central calls the cluster manager to create the resource (here the seam mints a
	`resource_id`; a real impl uses the id the cluster manager returns), then writes
	the price-lock at the catalog rate for the team's currency + cluster. Because the
	one component both provisions and locks, the rate shown is the rate locked — no
	agent push, no reconciliation gap. Returns the subscription + the locked handles.
	"""
	from central.billing.platform.sync import record_usage_events

	sub = create_subscription(
		team, cluster, plan, billing_cycle=billing_cycle, start_date=start_date,
		default_payment_method=default_payment_method, gateway=gateway, changed_by=changed_by,
	)

	currency = frappe.db.get_value("Billing Profile", team, "currency") or "INR"
	shown_rate = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
	resource_id = resource_id or f"res-{frappe.generate_hash(length=10)}"
	effective_from = f"{sub.start_date} 00:00:00"

	record_usage_events([{
		"event_id": f"prov-{sub.name}-{resource_id}",
		"team": team, "resource_id": resource_id, "cluster": cluster, "plan": plan,
		"shown_rate": shown_rate, "currency": currency,
		"event_type": "subscribed", "effective_from": effective_from, "effective_to": None,
	}])

	return {"subscription": sub.name, "resource_id": resource_id,
			"shown_rate": shown_rate, "currency": currency}


def change_plan(subscription: str, new_plan: str, changed_by: str | None = None):
	"""Change the requested plan (intent). Central writes a new price-lock segment
	when it reprovisions (ADR 0006); this records the contract change only."""
	doc = frappe.get_doc("Subscription", subscription)
	old_plan = doc.plan
	if new_plan == old_plan:
		return doc
	doc.plan = new_plan
	doc.save(ignore_permissions=True)
	_record_change(subscription, "Plan Changed", old_plan, new_plan, changed_by)
	return doc


def change_payment_method(subscription: str, new_method: str, changed_by: str | None = None):
	doc = frappe.get_doc("Subscription", subscription)
	old_method = doc.default_payment_method
	doc.default_payment_method = new_method
	doc.save(ignore_permissions=True)
	_record_change(subscription, "Payment Method Changed", old_method, new_method, changed_by)
	return doc


def cancel_subscription(subscription: str, changed_by: str | None = None):
	"""Cancel the subscription intent. The contract record is kept; the
	cancellation is logged. Stopping/terminating the running resource is a separate
	operational step Central drives via the cluster manager (ADR 0006)."""
	_record_change(subscription, "Cancelled", changed_by=changed_by)
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


def reconcile_subscription_resource(subscription: str, resource_id: str) -> dict:
	"""Reconcile a subscription's intent against the price-lock Central wrote when it
	provisioned the resource (keyed by `resource_id`). A missing lock means the
	resource hasn't been provisioned yet (intent outstanding); a plan mismatch is
	surfaced for follow-up.
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


# Deprecated agent-era name — agentless, Central writes the lock at provision time.
reconcile_with_agent_event = reconcile_subscription_resource
