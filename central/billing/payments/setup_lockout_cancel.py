# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Close the open gateway setups and top-ups of a team, or a user, that must wait."""

import frappe

from central.billing.gateways.base import GatewayUnsupported
from central.billing.payments import setup_lockout
from central.billing.platform.jobs import each_isolated
from central.billing.states import transition

JOB = "Setup lock cancel"
ACTOR = "setup lockout"
REASON = "setup cancelled after too many failed attempts"
CLOSED = ("canceled", "expired")


def close_open(team: str, user: str | None = None) -> dict:
	"""Cancel at the gateway the open setups and top-ups of the team while it waits, and
	the user's own open ones in each team where the user waits.

	An open Stripe dialog could keep trying cards, so its intent is cancelled. A Razorpay
	order cannot be cancelled, but a new one needs our server, which checks the wait."""
	scopes = _scopes(team, user)
	return {
		"setups": each_isolated(JOB, "Payment Method", _open_methods(scopes), close_setup),
		"top_ups": each_isolated(JOB, "Top-up Order", _open_orders(scopes), close_top_up),
	}


def close_setup(name: str) -> str:
	"""Cancel one setup at the gateway, then move it to Cancelled. A setup the gateway
	could not close (it succeeded or is processing) is left for its confirm to finish."""
	method = frappe.get_doc("Payment Method", name)
	status = _cancel_at_gateway(method.gateway, "cancel_setup", method.setup_reference)
	if status not in CLOSED:
		return status
	method = frappe.get_doc("Payment Method", name, for_update=True)
	if method.status != "Pending Validation":
		return method.status
	transition(method, "Cancelled", actor=ACTOR, reason=REASON)
	# Only billing code changes a method's status; this job runs as the system.
	method.save(ignore_permissions=True)
	return "Cancelled"


def close_top_up(name: str) -> str:
	"""Cancel one top-up's payment at the gateway, then expire the order. A payment that
	still lands can credit it: Expired moves to Credited."""
	order = frappe.get_doc("Top-up Order", name)
	status = _cancel_at_gateway(order.gateway, "cancel_order", order.gateway_order_id)
	if status not in CLOSED:
		return status
	frappe.db.get_value("Top-up Order", name, "name", for_update=True)
	order.reload()
	if order.status != "Created":
		return order.status
	order.expire(actor=ACTOR, reason=REASON)
	return "Expired"


def _scopes(team: str, user: str | None) -> list[dict]:
	"""Filters for the records to close: the team's, and the user's own in each team where
	they wait. A clear on one team ends only that team's wait, so it is read per team."""
	scopes = []
	if setup_lockout.Lockout.for_team(team).get_wait():
		scopes.append({"team": team})
	if setup_lockout.is_person(user):
		lockouts = setup_lockout.Lockout.for_user_in_teams(user, sorted(_open_teams(user)))
		teams = [name for name, lockout in lockouts.items() if lockout.get_wait()]
		if teams:
			scopes.append({"owner": user, "team": ["in", teams]})
	return scopes


def _open_teams(user: str) -> set[str]:
	methods = frappe.get_all("Payment Method", _open_method_filters({"owner": user}), pluck="team")
	orders = frappe.get_all("Top-up Order", _open_order_filters({"owner": user}), pluck="team")
	return {*methods, *orders}


def _open_methods(scopes: list[dict]) -> list[str]:
	names = [frappe.get_all("Payment Method", _open_method_filters(s), pluck="name") for s in scopes]
	return sorted({name for group in names for name in group})


def _open_orders(scopes: list[dict]) -> list[str]:
	names = [frappe.get_all("Top-up Order", _open_order_filters(s), pluck="name") for s in scopes]
	return sorted({name for group in names for name in group})


def _open_method_filters(scope: dict) -> dict:
	"""A setup the customer has not finished: no card saved on it yet."""
	return {
		**scope,
		"status": "Pending Validation",
		"setup_reference": ["is", "set"],
		"gateway_method_id": ["in", [None, ""]],
	}


def _open_order_filters(scope: dict) -> dict:
	return {**scope, "status": "Created", "gateway_order_id": ["is", "set"]}


def _cancel_at_gateway(gateway: str, action: str, reference: str) -> str:
	"""The gateway's status for the object after the cancel. A gateway that cannot cancel
	(Razorpay, PayPal) leaves the record as it is."""
	from central.billing.gateways.registry import get_adapter

	adapter = get_adapter(frappe.get_doc("Payment Gateway", gateway))
	try:
		return getattr(adapter, action)(reference)
	except GatewayUnsupported:
		return "unsupported"
