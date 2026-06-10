# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""ERPNext Sales Invoice sync — async, one-way, non-blocking (issue #17).

After a billable invoice is Paid, a background job pushes a Sales Invoice to
ERPNext (the statutory accounting SOR). Cloud Billing stays the SOR for the
customer-facing balance, so this sync is **strictly outbound** and **failure
isolated**: an ERPNext outage never blocks or rolls back the customer invoice —
it stays Paid, the failure is recorded, and the sync is retried with
exponential backoff (3 attempts) before ops is alerted.

Corrections (refund credit notes, #15) flow *down* the same outbound channel;
nothing is ever read back from ERPNext into billing.
"""

import frappe
import requests

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 60  # 60s, 120s, 240s


def enqueue_invoice_sync(invoice: str):
	"""Post-payment hook: queue the ERPNext sync after the transaction commits."""
	frappe.enqueue(
		"central.billing.revenue.erpnext_sync.sync_invoice",
		invoice=invoice,
		enqueue_after_commit=True,
		queue="long",
	)


@frappe.whitelist()
def sync_invoice(invoice: str) -> dict:
	"""Create the ERPNext Sales Invoice for a Paid invoice (idempotent, one-way).

	Never raises into the caller and never touches the customer invoice's
	status — the sync state lives in its own fields.
	"""
	inv = frappe.get_doc("Invoice", invoice)
	if inv.invoice_type != "Billable":
		return {"skipped": "not_billable"}  # cost_report is not a statutory sale
	if inv.status != "Paid":
		return {"skipped": "not_paid"}
	if inv.erpnext_invoice:
		return {"skipped": "already_synced"}  # one-way + idempotent

	attempt = (inv.erpnext_sync_attempts or 0) + 1
	try:
		erpnext_name = _post_sales_invoice(_build_sales_invoice(inv))
	except Exception as e:  # noqa: BLE001 — failure must be isolated, never re-raised
		return _handle_failure(invoice, attempt, str(e))

	frappe.db.set_value(
		"Invoice",
		invoice,
		{
			"erpnext_invoice": erpnext_name,
			"erpnext_sync_status": "Synced",
			"erpnext_sync_attempts": attempt,
			"erpnext_sync_error": None,
			"erpnext_next_retry_at": None,
		},
	)
	return {"synced": erpnext_name, "attempt": attempt}


def _handle_failure(invoice: str, attempt: int, error: str) -> dict:
	"""Record a failed attempt; schedule a backoff retry or alert ops. The
	customer invoice is never rolled back — it stays Paid."""
	values = {"erpnext_sync_attempts": attempt, "erpnext_sync_error": error[:140]}
	if attempt >= MAX_ATTEMPTS:
		values["erpnext_sync_status"] = "Failed"
		values["erpnext_next_retry_at"] = None
		frappe.db.set_value("Invoice", invoice, values)
		_alert_ops(invoice, error)
		return {"failed": error, "attempts": attempt}

	backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
	values["erpnext_sync_status"] = "Pending"
	values["erpnext_next_retry_at"] = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), seconds=backoff
	)
	frappe.db.set_value("Invoice", invoice, values)
	return {"retry_scheduled": True, "attempt": attempt, "backoff_seconds": backoff}


def retry_failed_syncs(now=None) -> list:
	"""Scheduler: re-run syncs whose backoff window has elapsed."""
	now = now or frappe.utils.now_datetime()
	due = frappe.get_all(
		"Invoice",
		filters=[
			["erpnext_sync_status", "=", "Pending"],
			["erpnext_next_retry_at", "is", "set"],
			["erpnext_next_retry_at", "<=", now],
		],
		pluck="name",
	)
	return [sync_invoice(name) for name in due]


# --- ERPNext transport ------------------------------------------------------


def _build_sales_invoice(inv) -> dict:
	"""Map a Cloud Billing invoice to an ERPNext Sales Invoice payload."""
	return {
		"doctype": "Sales Invoice",
		"customer": inv.team,
		"posting_date": str(inv.period_end),
		"currency": inv.currency,
		"cloud_billing_invoice": inv.name,  # back-reference for reconciliation
		"items": [
			{
				"item_name": f"{li.plan or li.resource_type or 'usage'} ({li.subscription_resource or ''})",
				"qty": li.days or li.quantity or 1,
				"rate": li.rate,
				"amount": li.amount,
			}
			for li in inv.items
		],
		"total": inv.subtotal,
		"grand_total": inv.total,
	}


def _post_sales_invoice(payload: dict) -> str:
	"""POST the Sales Invoice to ERPNext; return its name. Raises on any failure."""
	base = (frappe.conf.get("erpnext_url") or "").rstrip("/")
	if not base:
		raise RuntimeError("erpnext_url is not configured")
	response = requests.post(
		f"{base}/api/resource/Sales Invoice",
		json=payload,
		headers=_erpnext_headers(),
		timeout=30,
	)
	response.raise_for_status()
	return (response.json().get("data") or {}).get("name")


def _erpnext_headers() -> dict:
	key = frappe.conf.get("erpnext_api_key")
	secret = frappe.conf.get("erpnext_api_secret")
	if key and secret:
		return {"Authorization": f"token {key}:{secret}"}
	return {}


def _alert_ops(invoice: str, error: str):
	"""After the retry budget is spent, surface the failure to ops (not the
	customer — their invoice is Paid and unaffected)."""
	frappe.log_error(
		title=f"ERPNext sync failed: {invoice}",
		message=f"Sales Invoice sync for {invoice} failed after {MAX_ATTEMPTS} attempts: {error}",
	)
	frappe.get_doc("Invoice", invoice).add_comment(
		"Info", f"ERPNext sync failed after {MAX_ATTEMPTS} attempts — queued for ops follow-up."
	)
