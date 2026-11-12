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
NOTICE = "Payment Method Setup Expired"
# Card and UPI setups only. PayPal setups are not offered in the console.
SETUP_METHOD_TYPES = ("Card", "UPI Autopay")
PAYPAL_GATEWAY = "Paypal"
# Each due setup with a reference costs one gateway read, so one run reads at most this many.
SETUPS_PER_RUN = 500


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
		limit=SETUPS_PER_RUN,
	)
	setups_by_team: dict[str, list[str]] = {}
	for row in due:
		setups_by_team.setdefault(row.team, []).append(row.name)

	def expire(team: str) -> dict:
		return expire_team_setups(team, setups_by_team[team])

	return {"expired": each_isolated("Setup expiry", "Team", list(setups_by_team), expire)}


def expire_team_setups(team: str, names: list[str]) -> dict:
	"""Expire the team's unfinished setups. One notice covers them all."""
	unfinished = [name for name in names if not _is_kept_pending(name)]
	expired = [method for method in map(_expire_setup, unfinished) if method]
	if expired:
		_notify(team, expired)
	return {"team": team, "expired": [method.name for method in expired]}


def _is_kept_pending(name: str) -> bool:
	"""True when the gateway says the setup finished, or cannot say now. A finished setup
	waits for its confirm; one the gateway cannot read is tried again next run."""
	row = frappe.db.get_value("Payment Method", name, ["gateway", "setup_reference"], as_dict=True)
	if not row.setup_reference:
		return False
	logger = frappe.logger("billing")
	try:
		saved = _adapter(row.gateway).read_finished_setup(row.setup_reference)
	except GatewayError as error:  # a timeout or an unsupported read is a GatewayError too
		logger.warning(f"setup expiry skipped {name}: the gateway could not be read ({error})")
		return True
	if saved:
		logger.info(f"setup expiry kept {name}: the gateway says the setup finished, awaiting its confirm")
	return bool(saved)


def _expire_setup(name: str):
	"""The setup, now Expired. None when it finished or failed meanwhile."""
	method = frappe.get_doc("Payment Method", name, for_update=True)
	if method.status != "Pending Validation":
		return None

	transition(method, "Expired", actor="scheduler", reason="setup not finished in time")
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
