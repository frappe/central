# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Operator alerts — the daily sweeps detect trouble; this is what pages a human.

Every alert here is a condition the system already knows about and cannot fix by
itself. Silence is the success case.
"""

import frappe

from central.billing.platform import invariants, metrics

# A webhook we failed to process is a settlement we have not applied. An hour is long
# enough to rule out a retry that is still in flight.
WEBHOOK_FAILED_HOURS = 1

# Past this, an in-flight attempt is one reconciliation has had every chance to answer.
ATTEMPT_STALE_HOURS = 24

# How long an unchanged alert stays quiet after being sent, so an unfixed problem does
# not mail the operators every hour.
REPEAT_AFTER_HOURS = 6

_CACHE_KEY = "billing:last_alert_digest"


def stale_attempts() -> list[dict]:
	"""Attempts still in flight long after reconciliation should have answered them."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-ATTEMPT_STALE_HOURS)
	return [
		{
			"alert": "stale_attempt",
			"subject": a.name,
			"team": a.team,
			"detail": f"{a.status} since {a.initiated_at}",
		}
		for a in frappe.get_all(
			"Payment Attempt",
			filters={"status": ["in", invariants.IN_FLIGHT], "initiated_at": ["<", cutoff]},
			fields=["name", "team", "status", "initiated_at"],
			limit=100,
		)
	]


def failed_webhooks() -> list[dict]:
	"""Webhooks that failed to process and have not been retried since."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-WEBHOOK_FAILED_HOURS)
	return [
		{
			"alert": "failed_webhook",
			"subject": e.name,
			"team": None,
			"detail": f"{e.gateway} {e.event_type}: {e.error}",
		}
		for e in frappe.get_all(
			"Webhook Event",
			filters={"status": "Failed", "creation": ["<", cutoff]},
			fields=["name", "gateway", "event_type", "error"],
			limit=100,
		)
	]


def invariant_violations() -> list[dict]:
	"""Money the system derives two ways and gets two answers for."""
	return [
		{"alert": "invariant", "subject": v.subject, "team": v.team, "detail": f"{v.check}: {v.detail}"}
		for v in invariants.audit()
	]


SOURCES = (invariant_violations, failed_webhooks, stale_attempts)


def collect() -> list[dict]:
	"""Every open alert. One broken source must not blind the others."""
	found = []
	for source in SOURCES:
		try:
			found.extend(source())
		except Exception:
			frappe.log_error(
				title=f"Billing alert source {source.__name__} failed", message=frappe.get_traceback()
			)
	return found


def operators() -> list[str]:
	"""Who gets paged: enabled System Managers."""
	return frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)


def _digest(alerts: list[dict]) -> str:
	counts: dict[str, int] = {}
	for a in alerts:
		counts[a["alert"]] = counts.get(a["alert"], 0) + 1
	return ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))


def _recently_sent(signature: str) -> bool:
	"""True if this exact digest already went out inside the repeat window."""
	return frappe.cache().get_value(_CACHE_KEY) == signature


def run_operator_alerts() -> dict:
	"""Hourly: mail the operators about anything the sweeps cannot resolve alone."""
	alerts = collect()
	if not alerts:
		frappe.cache().delete_value(_CACHE_KEY)
		metrics.emit("billing.alerts", open=0)
		return {"alerts": 0, "notified": False}

	signature = _digest(alerts)
	metrics.emit("billing.alerts", open=len(alerts), digest=signature)
	if _recently_sent(signature):
		return {"alerts": len(alerts), "notified": False, "reason": "already sent"}

	recipients = operators()
	if recipients:
		frappe.sendmail(
			recipients=recipients,
			subject=f"Billing needs attention: {signature}",
			message=frappe.as_json(alerts[:50], indent=1),
			delayed=True,
		)
	frappe.cache().set_value(_CACHE_KEY, signature, expires_in_sec=REPEAT_AFTER_HOURS * 3600)
	frappe.log_error(
		title=f"Billing operator alert: {signature}", message=frappe.as_json(alerts[:50], indent=1)
	)
	return {"alerts": len(alerts), "notified": bool(recipients), "digest": signature}
