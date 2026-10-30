# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Operator alerts — the daily sweeps detect trouble; this is what pages a human.

Every alert here is a condition the system already knows about and cannot fix by
itself. Silence is the success case.
"""

import frappe
import requests

from central.billing import settings
from central.billing.payments import decline
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

RAVEN_SEND_PATH = "/api/method/raven.api.raven_message.send_message"
RAVEN_TIMEOUT_SECONDS = (5, 10)

# One message or email carries at most this many alerts; the Error Log keeps them all.
MAX_ROWS = 50


def stale_attempts() -> list[dict]:
	"""Attempts still in flight long after reconciliation should have answered them."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-ATTEMPT_STALE_HOURS)
	return [
		{
			"alert": "stale_attempt",
			"doctype": "Payment Attempt",
			"subject": a.name,
			"team": a.team,
			"detail": f"{a.status} since {a.initiated_at}",
		}
		for a in invariants.unheld_attempts_in_flight(
			cutoff, ["name", "team", "status", "initiated_at"], limit=100
		)
	]


def failed_webhooks() -> list[dict]:
	"""Webhooks that failed to process and have not been retried since."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-WEBHOOK_FAILED_HOURS)
	return [
		{
			"alert": "failed_webhook",
			"doctype": "Webhook Event",
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
		{
			"alert": "invariant",
			"doctype": v.subject_doctype,
			"subject": v.subject,
			"team": v.team,
			"detail": f"{v.check}: {v.detail}",
		}
		for v in invariants.audit()
	]


def readiness_gaps() -> list[dict]:
	"""What the next billing run would bill wrongly or not at all."""
	from central.billing.platform import readiness

	return [
		{
			"alert": "readiness",
			"doctype": v.subject_doctype,
			"subject": v.subject,
			"team": v.team,
			"detail": f"{v.check}: {v.detail}",
		}
		for v in invariants.audit(checks=readiness.CHECKS)
	]


def held_invoices() -> list[dict]:
	"""Bills still unissued long after their period closed — missing billing details,
	accounting records that never synced, or a GSTIN never checked.

	This is money we are not collecting on resources that are still running, and
	nothing else surfaces it: the invoice stays Draft, so dunning never sees it.
	"""
	from central.billing.revenue.invoicing.lifecycle import held_drafts

	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -settings.billing_details_grace_days())
	return [
		{
			"alert": "held_invoice",
			"doctype": "Invoice",
			"subject": i.name,
			"team": i.team,
			"detail": f"{i.currency} {i.total} still unissued ({i.hold_reason or 'not opened'}), period closed {i.period_end}",
		}
		for i in held_drafts(held_before=cutoff, limit=100)
	]


def suspended_servers_running() -> list[dict]:
	"""Servers dunning suspended but could not stop. The team is not paying for them."""
	sub = frappe.qb.DocType("Subscription")
	vm = frappe.qb.DocType("Virtual Machine")
	rows = (
		frappe.qb.from_(sub)
		.join(vm)
		.on(sub.server_id == vm.name)
		.select(sub.name, sub.team, sub.server_id)
		.where((sub.account_standing == "Suspended") & (vm.status == "Running"))
		.limit(100)
	).run(as_dict=True)
	return [
		{
			"alert": "suspended_server_running",
			"doctype": "Subscription",
			"subject": r.name,
			"team": r.team,
			"detail": f"Server {r.server_id} is suspended for non-payment but still running",
		}
		for r in rows
	]


def termination_due() -> list[dict]:
	"""Overdue invoices past the termination day. A person decides; nothing is deleted for them."""
	from central.billing.revenue import dunning

	policy = dunning.dunning_policy()
	today = frappe.utils.nowdate()
	found = []
	for invoice in frappe.get_all(
		"Invoice",
		filters={"invoice_type": "Billable", "status": "Overdue"},
		fields=["name", "team", "currency", "total", "due_date", "dunning_starts_on"],
		limit=100,
	):
		schedule = dunning.dunning_schedule(dunning.dunning_clock_start(invoice), policy)
		if "Terminate" in dunning.stages_reached(schedule, today):
			found.append(
				{
					"alert": "termination_due",
					"doctype": "Invoice",
					"subject": invoice.name,
					"team": invoice.team,
					"detail": f"{invoice.currency} {invoice.total} unpaid since {invoice.due_date}; termination is due",
				}
			)
	return found


def failed_refunds() -> list[dict]:
	"""Refunds a gateway refused. The invoice is cancelled but the customer is still owed."""
	return [
		{
			"alert": "failed_refund",
			"doctype": "Invoice",
			"subject": r.invoice,
			"team": r.team,
			"detail": f"{r.currency} {r.amount} not refunded ({r.name}); retry it from the invoice",
		}
		for r in frappe.get_all(
			"Refund",
			filters={"status": "Failed"},
			fields=["name", "invoice", "team", "currency", "amount"],
			limit=100,
		)
	]


def unsettled_captures() -> list[dict]:
	"""Money a gateway took for an invoice that is still unpaid a day later.

	The capture webhook was lost, and reconciliation could not confirm the payment at the gateway.
	"""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-ATTEMPT_STALE_HOURS)
	attempt = frappe.qb.DocType("Payment Attempt")
	invoice = frappe.qb.DocType("Invoice")
	captures = (
		frappe.qb.from_(attempt)
		.join(invoice)
		.on(invoice.name == attempt.invoice)
		.select(attempt.name, attempt.team, attempt.currency, attempt.amount, attempt.invoice)
		.where(
			(attempt.status == "Captured")
			& invoice.status.isin(("Open", "Overdue"))
			& (attempt.initiated_at < cutoff)
		)
		.limit(100)
		.run(as_dict=True)
	)
	return [
		{
			"alert": "unsettled_capture",
			"doctype": "Payment Attempt",
			"subject": a.name,
			"team": a.team,
			"detail": f"{a.currency} {a.amount} captured, but invoice {a.invoice} is still unpaid",
		}
		for a in captures
	]


def refused_charges() -> list[dict]:
	"""Charges a gateway would not create because our request was wrong, on invoices still unpaid.
	No retry fixes these; the request or the billing profile must be corrected."""
	attempt = frappe.qb.DocType("Payment Attempt")
	invoice = frappe.qb.DocType("Invoice")
	refused = (
		frappe.qb.from_(attempt)
		.join(invoice)
		.on(invoice.name == attempt.invoice)
		.select(attempt.name, attempt.team, attempt.invoice, attempt.failure_reason)
		.where((attempt.failure_code == decline.REQUEST_REFUSED) & invoice.status.isin(("Open", "Overdue")))
		.limit(100)
		.run(as_dict=True)
	)
	return [
		{
			"alert": "refused_charge",
			"doctype": "Payment Attempt",
			"subject": a.name,
			"team": a.team,
			"detail": f"Gateway refused the charge for {a.invoice}: {a.failure_reason}",
		}
		for a in refused
	]


def failed_accounting_syncs() -> list[dict]:
	"""Paid invoices the accounting sync gave up on. The customer is not affected; the books are short."""
	return [
		{
			"alert": "failed_accounting_sync",
			"doctype": "Invoice",
			"subject": i.name,
			"team": i.team,
			"detail": f"Accounting sync failed: {i.erpnext_sync_error}",
		}
		for i in frappe.get_all(
			"Invoice",
			filters={"erpnext_sync_status": "Failed"},
			fields=["name", "team", "erpnext_sync_error"],
			limit=100,
		)
	]


SOURCES = (
	invariant_violations,
	readiness_gaps,
	failed_webhooks,
	stale_attempts,
	unsettled_captures,
	refused_charges,
	held_invoices,
	failed_refunds,
	failed_accounting_syncs,
	suspended_servers_running,
	termination_due,
)


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


def notify_operators(title: str, alerts: list[dict]) -> list[str]:
	"""Send alerts to the channel set in Billing Settings and return where they went.

	A failed Raven post falls back to the alert email addresses, so an alert is not dropped.
	"""
	channel = settings.operator_alert_channel()
	sent_to = []
	if "Raven" in channel and _post_to_raven(title, alerts):
		sent_to.append("Raven")
	if ("Email" in channel or not sent_to) and _email(title, alerts):
		sent_to.append("Email")
	return sent_to


def _post_to_raven(title: str, alerts: list[dict]) -> bool:
	"""Post the alerts to the Raven channel as the bot user. Log and return False on failure."""
	raven = settings.raven_connection()
	if not raven:
		frappe.log_error(
			title="Billing operator alert not posted to Raven", message="Raven is not configured."
		)
		return False

	try:
		response = requests.post(
			raven["site_url"] + RAVEN_SEND_PATH,
			headers={"Authorization": f"token {raven['api_key']}:{raven['api_secret']}"},
			json={"channel_id": raven["channel_id"], "text": _raven_message(title, alerts)},
			timeout=RAVEN_TIMEOUT_SECONDS,
		)
		response.raise_for_status()
	except requests.RequestException as error:
		frappe.log_error(title="Billing operator alert not posted to Raven", message=str(error))
		return False
	return True


def _email(title: str, alerts: list[dict]) -> bool:
	"""Mail the alerts to the named addresses. Return False when there are none."""
	recipients = settings.operator_alert_emails()
	if not recipients:
		return False

	frappe.sendmail(
		recipients=recipients,
		subject=title,
		template="operator_alert",
		args={"count": len(alerts), "rows": [_row(alert) for alert in alerts[:MAX_ROWS]]},
		delayed=True,
	)
	return True


def _raven_message(title: str, alerts: list[dict]) -> str:
	"""The alerts as Raven message HTML: the title, then one line for each alert."""
	rows = [_row(alert) for alert in alerts[:MAX_ROWS]]
	lines = "".join(f"<li><code>{kind}</code> {reference}: {detail}</li>" for kind, reference, detail in rows)
	hidden = len(alerts) - MAX_ROWS
	footer = f"<p>{hidden} more alerts are in the Error Log.</p>" if hidden > 0 else ""
	return f"<p><strong>{frappe.utils.escape_html(title)}</strong></p><ul>{lines}</ul>{footer}"


def _row(alert: dict) -> list[str]:
	"""Kind, reference and detail as escaped HTML, because a detail can carry a gateway error.

	The reference links to the record in Desk when the alert names its DocType.
	"""
	escape = frappe.utils.escape_html
	reference = escape(str(alert["subject"]))
	if alert.get("doctype") and alert["subject"]:
		url = frappe.utils.get_url_to_form(alert["doctype"], alert["subject"])
		reference = f'<a href="{escape(url)}">{reference}</a>'
	if alert["team"]:
		reference += f" ({escape(str(alert['team']))})"
	return [escape(str(alert["alert"])), reference, escape(str(alert["detail"]))]


def _digest(alerts: list[dict]) -> str:
	counts: dict[str, int] = {}
	for a in alerts:
		counts[a["alert"]] = counts.get(a["alert"], 0) + 1
	return ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))


def _recently_sent(signature: str) -> bool:
	"""True if this exact digest already went out inside the repeat window."""
	return frappe.cache().get_value(_CACHE_KEY) == signature


def run_operator_alerts() -> dict:
	"""Hourly: tell the operators about anything the sweeps cannot resolve alone."""
	alerts = collect()
	if not alerts:
		frappe.cache().delete_value(_CACHE_KEY)
		metrics.emit("billing.alerts", open=0)
		return {"alerts": 0, "notified": False}

	signature = _digest(alerts)
	metrics.emit("billing.alerts", open=len(alerts), digest=signature)
	if _recently_sent(signature):
		return {"alerts": len(alerts), "notified": False, "reason": "already sent"}

	sent_to = notify_operators(f"Billing needs attention: {signature}", alerts)
	frappe.cache().set_value(_CACHE_KEY, signature, expires_in_sec=REPEAT_AFTER_HOURS * 3600)
	frappe.log_error(title=f"Billing operator alert: {signature}", message=frappe.as_json(alerts, indent=1))
	return {"alerts": len(alerts), "notified": bool(sent_to), "sent_to": sent_to, "digest": signature}
