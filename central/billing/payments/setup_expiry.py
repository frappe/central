# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from pypika.terms import ExistsCriterion

from central.billing.gateways.base import GatewayError
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated
from central.billing.states import transition

SETUP_EXPIRES_HOURS = 24
# A setup still pending this long is released and expired quietly, whatever the gateway says.
SETUP_RELEASE_DAYS = 7
# A setup cancelled by a new one is released this late, so a retry with the same card can
# finish first and keep the shared token.
CANCELLED_SETUP_RELEASE_DELAY_MINUTES = 30
NOTICE = "Payment Method Setup Expired"
# Card and UPI setups only. PayPal setups are not offered in the console.
SETUP_METHOD_TYPES = ("Card", "UPI Autopay")
PAYPAL_GATEWAY = "Paypal"
# Each due setup with a reference costs one gateway read, so one run reads at most this many.
# Oldest first: a row the gateway cannot read reaches the release age and leaves the queue.
SETUPS_PER_RUN = 500
# A release that has not finished is tried again every hour for this long, then left to an operator.
RELEASE_RETRY_DAYS = 7
# Untranslated, so the comment always starts with it and a second give-up is never written.
GIVE_UP_NOTE = "This setup's release at the gateway did not finish in time."
# A team gets at most one expiry notice in this many hours.
NOTICE_COOLDOWN_HOURS = 24


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
	"""Settle the team's unfinished setups. One notice covers the ones that expired,
	except those released for age, which expire quietly."""
	expired = [method for method in (_settle_setup(name, release_before) for name in names) if method]
	noticed = _expired_since(expired, release_before)
	if noticed:
		_notify(team, noticed)
	return {"team": team, "expired": [method.name for method in expired]}


def _expired_since(expired: list, release_before) -> list:
	"""The expired setups started after `release_before`."""
	if not release_before:
		return expired
	return [method for method in expired if method.creation > release_before]


def _settle_setup(name: str, release_before):
	"""The setup, if it expired now. A Razorpay setup the gateway proves finished is
	activated. A card the gateway saved but nobody confirmed is removed and expired."""
	row = frappe.db.get_value(
		"Payment Method", name, ["gateway", "setup_reference", "creation"], as_dict=True
	)
	if release_before and row.creation <= release_before:
		return expire_and_release(name, f"setup still unfinished after {SETUP_RELEASE_DAYS} days")
	saved = _read_setup(name, row)
	if saved is None:
		return None
	if saved.get("payment"):
		return _activate_mandate(name, saved["payment"])
	if saved.get("payment_method"):
		return expire_and_release(name, "setup saved at the gateway but never confirmed")
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


def _activate_mandate(name: str, payment: dict):
	"""The setup, if the proof expired it instead (another method holds its token)."""
	from central.billing.payments import mandates

	method = mandates.activate_proven_mandate(name, payment, actor="scheduler")
	return method if method.status == "Expired" else None


def expire_and_release(name: str, reason: str, actor: str = "scheduler"):
	"""Expire the setup, then queue giving back what it saved at the gateway."""
	method = _expire_setup(name, reason=reason, actor=actor)
	if method:
		queue_late_release(method)
	return method


def _expire_setup(name: str, reason: str = "setup not finished in time", actor: str = "scheduler"):
	"""The setup, now Expired. None when it finished or failed meanwhile."""
	method = frappe.get_doc("Payment Method", name, for_update=True)
	if method.status != "Pending Validation":
		return None

	transition(method, "Expired", actor=actor, reason=reason)
	# The hourly job runs as the system with no session user to check.
	method.save(ignore_permissions=True)
	return method


def queue_late_release(method) -> None:
	"""Queue giving back what a setup saved at the gateway after it expired or was
	cancelled here."""
	if not is_released_setup(method):
		return

	frappe.enqueue(
		"central.billing.payments.setup_expiry.release_late_setup",
		payment_method=method.name,
		job_id=f"late-setup-release::{method.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def release_late_setup(payment_method: str) -> None:
	"""Give back what a setup saved at the gateway after it expired or was cancelled here:
	refund its captured authorisation payment, then remove its card or token. Each step is
	safe to repeat, so a failed release is tried again until `setup_released_at` is set.
	The status does not change."""
	method = frappe.get_doc("Payment Method", payment_method)
	if not is_released_setup(method):
		return
	adapter = _adapter(method.gateway)
	saved = adapter.read_finished_setup(method.setup_reference)
	payment = saved.get("payment") or {}
	if payment.get("status") == "authorized":
		return  # The setup order captures it by itself; the next try refunds the capture.

	if payment.get("status") == "captured":
		from central.billing.payments import mandates

		mandates.refund_authorisation(method, payment["id"], frappe.utils.flt(payment.get("amount")) / 100)
	if saved.get("payment_method"):
		_remove_saved_method(method, adapter, saved["payment_method"], saved.get("customer"))
	frappe.db.set_value(
		"Payment Method", method.name, "setup_released_at", frappe.utils.now_datetime(), update_modified=False
	)


def retry_unfinished_releases(now=None) -> dict:
	"""Queue the release for setups whose release has not finished. A cancelled setup is
	first queued here, `CANCELLED_SETUP_RELEASE_DELAY_MINUTES` after it was cancelled. One
	still unfinished `RELEASE_RETRY_DAYS` after the setup ended gets one comment and no more tries."""
	now = now or frappe.utils.now_datetime()
	give_up_before = frappe.utils.add_to_date(now, days=-RELEASE_RETRY_DAYS)
	cancelled_before = frappe.utils.add_to_date(now, minutes=-CANCELLED_SETUP_RELEASE_DELAY_MINUTES)
	# The row changes last when it expires or is cancelled; the release leaves `modified` alone.
	method = frappe.qb.DocType("Payment Method")
	ended = method.modified
	settled = (method.status != "Cancelled") | (ended <= cancelled_before)
	due = _unreleased_setups((ended >= give_up_before) & settled)
	retried = each_isolated("Setup release retry", "Payment Method", due, _queue_release)
	stale = _unreleased_setups((ended < give_up_before) & _give_up_comments().negate())
	each_isolated("Setup release give-up", "Payment Method", stale, _give_up_release)
	return {"retried": retried, "given_up": stale}


def _queue_release(name: str) -> str:
	queue_late_release(frappe.get_doc("Payment Method", name))
	return name


def _give_up_release(name: str) -> None:
	advice = _("Refund its authorisation and remove its card or token at the gateway by hand.")
	frappe.get_doc("Payment Method", name).add_comment("Comment", f"{GIVE_UP_NOTE} {advice}")


def _unreleased_setups(condition) -> list[str]:
	"""Released setups whose release has not finished, oldest first."""
	method = frappe.qb.DocType("Payment Method")
	return (
		frappe.qb.from_(method)
		.select(method.name)
		.where(method.status.isin(["Expired", "Cancelled"]))
		.where(method.validated_at.isnull())
		.where(method.setup_reference.notnull() & (method.setup_reference != ""))
		.where(method.setup_released_at.isnull())
		.where(condition)
		.orderby(method.modified)
		.limit(SETUPS_PER_RUN)
		.run(pluck=True)
	)


def _give_up_comments():
	method = frappe.qb.DocType("Payment Method")
	comment = frappe.qb.DocType("Comment")
	return ExistsCriterion(
		frappe.qb.from_(comment)
		.select(comment.name)
		.where(comment.reference_doctype == "Payment Method")
		.where(comment.reference_name == method.name)
		.where(comment.content.like(f"{GIVE_UP_NOTE}%"))
	)


def _remove_saved_method(method, adapter, method_id: str, customer: str | None) -> None:
	"""Remove the card or token a late setup saved, so it can never be charged. One that
	another method also holds is kept. A failure raises, and the release is tried again."""
	if _is_held_by_another_method(method, method_id):
		method.add_comment(
			"Comment", _("Kept {0}: another payment method uses it at the gateway.").format(method_id)
		)
		return

	adapter.remove_saved_method(method_id, customer_reference=customer or method.gateway_customer_id)
	method.add_comment(
		"Comment", _("Removed {0}, saved at the gateway after the setup expired.").format(method_id)
	)


def is_released_setup(method) -> bool:
	"""True for a setup that expired or was cancelled before it was ever validated, and
	that the gateway may have saved something for."""
	return (
		method.status in ("Expired", "Cancelled") and not method.validated_at and bool(method.setup_reference)
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
	if has_active_method_since(team, latest.creation) or has_recent_notice(team):
		return

	notifications.notify(
		team,
		NOTICE,
		reference_doctype="Payment Method",
		reference_name=latest.name,
	)


def has_recent_notice(team: str) -> bool:
	"""True when the team was sent an expiry notice in the last `NOTICE_COOLDOWN_HOURS`."""
	since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-NOTICE_COOLDOWN_HOURS)
	return bool(
		frappe.db.exists(
			"Billing Notification Log", {"team": team, "event_type": NOTICE, "creation": [">=", since]}
		)
	)


def has_active_method_since(team: str, since) -> bool:
	"""True when the team has a working method that was added after `since`."""
	return bool(
		frappe.db.exists(
			"Payment Method",
			{"team": team, "status": "Active", "validated_at": [">=", since]},
		)
	)
