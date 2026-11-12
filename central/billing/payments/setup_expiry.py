# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.doctype.payment_method.payment_method import is_expired_setup
from central.billing.gateways.base import GatewayError
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated
from central.billing.states import transition

SETUP_EXPIRES_HOURS = 24
# A setup still pending this long is released and expired, whatever the gateway says.
SETUP_RELEASE_DAYS = 7
NOTICE = "Payment Method Setup Expired"
# Card and UPI setups only. PayPal setups are not offered in the console.
SETUP_METHOD_TYPES = ("Card", "UPI Autopay")
PAYPAL_GATEWAY = "Paypal"
# Each due setup with a reference costs one gateway read, so one run reads at most this many.
# Oldest first: a row the gateway cannot read reaches the release age and leaves the queue.
SETUPS_PER_RUN = 500


def expire_unfinished_setups(now=None) -> dict:
	"""Settle card and UPI setups left unfinished for a day, and tell each team once."""
	now = now or frappe.utils.now_datetime()
	cutoff = frappe.utils.add_to_date(now, hours=-SETUP_EXPIRES_HOURS)
	release_before = frappe.utils.add_to_date(now, days=-SETUP_RELEASE_DAYS)
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
		limit=SETUPS_PER_RUN,
	)
	setups_by_team: dict[str, list[str]] = {}
	for row in due:
		setups_by_team.setdefault(row.team, []).append(row.name)

	def expire(team: str) -> dict:
		return expire_team_setups(team, setups_by_team[team], release_before)

	return {"expired": each_isolated("Setup expiry", "Team", list(setups_by_team), expire)}


def expire_team_setups(team: str, names: list[str], release_before=None) -> dict:
	"""Settle the team's unfinished setups. One notice covers the ones that expired."""
	expired = [method for method in (_settle_setup(name, release_before) for name in names) if method]
	if expired:
		_notify(team, expired)
	return {"team": team, "expired": [method.name for method in expired]}


def _settle_setup(name: str, release_before):
	"""The setup, if it expired now. A Razorpay setup the gateway proves finished is
	activated. A card the gateway saved but nobody confirmed is removed and expired."""
	row = frappe.db.get_value(
		"Payment Method", name, ["gateway", "setup_reference", "creation"], as_dict=True
	)
	if release_before and row.creation <= release_before:
		return _expire_and_release(name, f"setup still unfinished after {SETUP_RELEASE_DAYS} days")
	saved = _read_setup(name, row)
	if saved is None:
		return None
	if saved.get("payment"):
		_activate_mandate(name, saved["payment"])
		return None
	if saved.get("payment_method"):
		return _expire_and_release(name, "setup saved at the gateway but never confirmed")
	return _expire_setup(name)


def _read_setup(name: str, row) -> dict | None:
	"""What the gateway says the setup saved. None when it cannot say now, so the
	row waits for the next run."""
	if not row.setup_reference:
		return {}
	try:
		return _adapter(row.gateway).read_finished_setup(row.setup_reference)
	except GatewayError as error:  # a timeout or an unsupported read is a GatewayError too
		frappe.logger("billing").warning(
			f"setup expiry skipped {name}: the gateway could not be read ({error})"
		)
		return None


def _activate_mandate(name: str, payment: dict) -> None:
	from central.billing.payments import mandates

	mandates.activate_proven_mandate(name, payment, actor="scheduler")


def _expire_and_release(name: str, reason: str):
	"""Expire the setup, then queue giving back what it saved at the gateway."""
	method = _expire_setup(name, reason=reason)
	if method:
		queue_late_release(method)
	return method


def _expire_setup(name: str, reason: str = "setup not finished in time"):
	"""The setup, now Expired. None when it finished or failed meanwhile."""
	method = frappe.get_doc("Payment Method", name, for_update=True)
	if method.status != "Pending Validation":
		return None

	transition(method, "Expired", actor="scheduler", reason=reason)
	# The hourly job runs as the system with no session user to check.
	method.save(ignore_permissions=True)
	return method


def queue_late_release(method) -> None:
	"""Queue giving back what a setup saved at the gateway after it expired here."""
	if not is_expired_setup(method) or not method.setup_reference:
		return

	frappe.enqueue(
		"central.billing.payments.setup_expiry.release_late_setup",
		payment_method=method.name,
		job_id=f"late-setup-release::{method.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def release_late_setup(payment_method: str) -> None:
	"""Refund the authorisation payment of a setup that finished after it expired, and
	queue the removal of its card or token. The method stays Expired."""
	from central.billing.payments import mandates

	method = frappe.get_doc("Payment Method", payment_method)
	if not is_expired_setup(method) or not method.setup_reference:
		return
	saved = _adapter(method.gateway).read_finished_setup(method.setup_reference)
	if not saved.get("payment_method"):
		return

	if saved.get("payment"):
		mandates._queue_authorisation_refund(method, saved["payment"])
	frappe.enqueue(
		"central.billing.payments.setup_expiry.remove_late_saved_method",
		payment_method=method.name,
		method_id=saved["payment_method"],
		customer_reference=saved.get("customer") or method.gateway_customer_id,
		job_id=f"late-setup-remove::{saved['payment_method']}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def remove_late_saved_method(payment_method: str, method_id: str, customer_reference: str | None) -> None:
	"""Remove the card or token a late setup saved, so it can never be charged.
	One that another method also holds is kept, and a failure fails the job."""
	method = frappe.get_doc("Payment Method", payment_method)
	if _is_held_by_another_method(method, method_id):
		method.add_comment(
			"Comment", _("Kept {0}: another payment method uses it at the gateway.").format(method_id)
		)
		return

	try:
		_adapter(method.gateway).remove_saved_method(method_id, customer_reference=customer_reference)
	except Exception as error:
		method.add_comment(
			"Comment",
			_("{0}, saved at the gateway after the setup expired, was not removed: {1}").format(
				method_id, error
			),
		)
		# The job's own rollback would drop the comment the operator needs.
		frappe.db.commit()
		raise
	method.add_comment(
		"Comment", _("Removed {0}, saved at the gateway after the setup expired.").format(method_id)
	)


def _is_held_by_another_method(method, method_id: str) -> bool:
	"""True when another live method on the gateway holds the same card or token.
	Razorpay gives the same card and customer the same token."""
	return bool(
		frappe.db.exists(
			"Payment Method",
			{
				"gateway": method.gateway,
				"gateway_method_id": method_id,
				"status": ["!=", "Cancelled"],
				"name": ["!=", method.name],
			},
		)
	)


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


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
