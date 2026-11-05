import frappe
from frappe.utils import add_to_date, now_datetime

from central.billing.platform.alerts import notify_operators


def alert_failed_signups() -> None:
	"""Hourly: tell the operators about signup site creations that failed in the last hour.
	A signup should never fail, so one failure is enough."""
	failed = frappe.get_all(
		"Resource Action",
		filters={
			"action": "create",
			"resource_type": "Site",
			"status": ["in", ("Failed", "Timed Out")],
			"completed_at": [">=", add_to_date(now_datetime(), hours=-1)],
		},
		fields=["name", "team", "error_code", "error_message"],
	)
	if not failed:
		return

	notify_operators(
		f"Signup failures in the last hour: {len(failed)}",
		[
			{
				"alert": row.error_code or "FAILED",
				"doctype": "Resource Action",
				"subject": row.name,
				"team": row.team,
				"detail": row.error_message or "",
			}
			for row in failed
		],
	)
