# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""GSTIN status: looked up from the GST portal, read from the Billing Profile.

Invoicing never looks a GSTIN up. It reads the stored status, which a paced,
capped daily sweep keeps fresh, so billing every Indian team costs the portal
nothing.
"""

import time

import frappe

from central.billing import settings

# Statuses that stop an invoice from carrying the GSTIN.
LAPSED = ("Inactive", "Suspended", "Cancelled", "Invalid")
KNOWN = ("Active", *LAPSED)

# Gap between two sweep lookups, and when the sweep gives up for the day.
PACE_SECONDS = 0.5
MAX_FAILURES_IN_A_ROW = 5
SWEEP_BUDGET_SECONDS = 20 * 60

# A customer's "check again" inside this window is answered from the store.
RECHECK_COOLDOWN_SECONDS = 10 * 60


def lookups_enabled() -> bool:
	"""Lookups go through ERPNext, so they are off when the sync is."""
	return bool(frappe.conf.get("enable_erpnext_sync"))


def standing(team: str) -> frappe._dict:
	"""The GSTIN an invoice may carry, and whether the portal last called it lapsed.

	A GSTIN that has not been checked yet is trusted.
	"""
	profile = (
		frappe.db.get_value("Billing Profile", team, ["gstin", "gst_status"], as_dict=True) or frappe._dict()
	)
	lapsed = bool(profile.gstin) and profile.gst_status in LAPSED
	return frappe._dict(gstin=None if lapsed else (profile.gstin or None), lapsed=lapsed)


def store(team: str, gstin: str, details: dict) -> None:
	"""Save what the portal said, unless the GSTIN changed while we asked."""
	values = {"gst_status_checked_at": frappe.utils.now_datetime()}
	status = (details.get("status") or "").strip().title()
	if status in KNOWN:
		values["gst_status"] = status
	else:
		frappe.logger("billing").warning(
			f"GSTIN status {status!r} for {team} not recognised, kept the old one"
		)
	if details.get("gst_category"):
		values["gst_category"] = details["gst_category"]
	frappe.db.set_value("Billing Profile", {"name": team, "gstin": gstin}, values, update_modified=False)


def refresh(team: str) -> str | None:
	"""Look the team's GSTIN up now and store the answer. Returns the stored status."""
	from central.billing.ingester.customer import get_gstin_details

	gstin = frappe.db.get_value("Billing Profile", team, "gstin")
	if not gstin or not lookups_enabled():
		return None
	details = get_gstin_details(gstin)
	if details:
		store(team, gstin, details)
	return frappe.db.get_value("Billing Profile", team, "gst_status")


def recheck(team: str) -> str | None:
	"""A customer's "check again". Repeats inside the cooldown cost no lookup."""
	checked_at, status = frappe.db.get_value(
		"Billing Profile", team, ["gst_status_checked_at", "gst_status"]
	) or (None, None)
	if checked_at and _seconds_since(checked_at) < RECHECK_COOLDOWN_SECONDS:
		return status
	return refresh(team)


def forget(profile) -> None:
	"""Drop the old GSTIN's status and look the new one up in the background."""
	profile.db_set(
		{"gst_status": None, "gst_category": None, "gst_status_checked_at": None}, update_modified=False
	)
	if not profile.gstin or not lookups_enabled():
		return
	frappe.enqueue(
		"central.billing.revenue.gst_status.refresh",
		queue="short",
		job_id=f"gst-status::{profile.name}",
		deduplicate=True,
		enqueue_after_commit=True,
		team=profile.name,
	)


def stale_teams(limit: int) -> list[str]:
	"""Teams with a GSTIN never checked or checked too long ago, oldest first."""
	profile = frappe.qb.DocType("Billing Profile")
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -settings.gst_status_refresh_days())
	return (
		frappe.qb.from_(profile)
		.select(profile.name)
		.where(profile.gstin.isnotnull() & (profile.gstin != ""))
		.where(profile.gst_status_checked_at.isnull() | (profile.gst_status_checked_at < cutoff))
		.orderby(profile.gst_status_checked_at)
		.limit(limit)
	).run(pluck=True)


def run_gst_status_refresh() -> None:
	"""Daily: queue the sweep, off the scheduler's own worker."""
	frappe.enqueue(
		"central.billing.revenue.gst_status.refresh_stale",
		queue="long",
		job_id="gst-status-refresh",
		deduplicate=True,
	)


def refresh_stale() -> dict:
	"""Look up stale statuses one at a time, paced, capped and time-boxed.

	Stops for the day after a run of failures: the portal or ERPNext is down, and
	asking harder would not help it.
	"""
	if not lookups_enabled():
		return {"checked": 0, "failed": 0, "skipped": "lookups_off"}
	started = time.monotonic()
	checked = failed = in_a_row = 0
	for team in stale_teams(settings.gst_status_daily_limit()):
		if time.monotonic() - started > SWEEP_BUDGET_SECONDS:
			break
		try:
			refresh(team)
			checked += 1
			in_a_row = 0
		except Exception:
			failed += 1
			in_a_row += 1
			frappe.log_error(
				title="GSTIN Status Lookup Failed", reference_doctype="Billing Profile", reference_name=team
			)
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each answer the portal gave
		if in_a_row >= MAX_FAILURES_IN_A_ROW:
			break
		time.sleep(PACE_SECONDS)
	return {"checked": checked, "failed": failed}


def _seconds_since(moment) -> float:
	return frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), moment)
