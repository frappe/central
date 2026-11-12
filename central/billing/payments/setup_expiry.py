# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated
from central.billing.states import transition

SETUP_EXPIRES_HOURS = 24
NOTICE = "Payment Method Setup Expired"
# Card and UPI setups only. PayPal setups are not offered in the console.
SETUP_METHOD_TYPES = ("Card", "UPI Autopay")
PAYPAL_GATEWAY = "Paypal"


def expire_unfinished_setups(now=None) -> dict:
	"""Expire card and UPI setups left unfinished for a day, and tell each team once."""
	cutoff = frappe.utils.add_to_date(now or frappe.utils.now_datetime(), hours=-SETUP_EXPIRES_HOURS)
	due = frappe.get_all(
		"Payment Method",
		filters={
			"status": "Pending Validation",
			"creation": ["<=", cutoff],
			"method_type": ["in", SETUP_METHOD_TYPES],
			"gateway": ["!=", PAYPAL_GATEWAY],
		},
		fields=["name", "team"],
		order_by="creation asc",
	)
	setups_by_team: dict[str, list[str]] = {}
	for row in due:
		setups_by_team.setdefault(row.team, []).append(row.name)

	def expire(team: str) -> dict:
		return expire_team_setups(team, setups_by_team[team])

	return {"expired": each_isolated("Setup expiry", "Team", list(setups_by_team), expire)}


def expire_team_setups(team: str, names: list[str]) -> dict:
	"""Expire the team's unfinished setups. One notice covers them all."""
	expired = [method for method in map(_expire_setup, names) if method]
	if expired:
		_notify(team, expired)
	return {"team": team, "expired": [method.name for method in expired]}


def _expire_setup(name: str):
	"""The setup, now Expired. None when it finished or failed meanwhile."""
	method = frappe.get_doc("Payment Method", name, for_update=True)
	if method.status != "Pending Validation":
		return None

	transition(method, "Expired", actor="scheduler", reason="setup not finished in time")
	# The hourly job runs as the system with no session user to check.
	method.save(ignore_permissions=True)
	return method


def _notify(team: str, expired: list) -> None:
	latest = max(expired, key=lambda method: method.creation)
	if has_active_method_since(team, latest.creation):
		return

	notifications.notify(
		team,
		NOTICE,
		reference_doctype="Payment Method",
		reference_name=latest.name,
	)


def has_active_method_since(team: str, since) -> bool:
	"""True when the team has a working method that was added after `since`."""
	return bool(
		frappe.db.exists(
			"Payment Method",
			{"team": team, "status": "Active", "validated_at": [">=", since]},
		)
	)
