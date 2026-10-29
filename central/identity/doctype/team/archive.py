import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import get_first_day, today

from central.signups.eligibility import has_active_payment_method


def get_archive_checks(team: str) -> list[dict]:
	"""What must be true before `team` can be archived, in the order an owner clears it.

	1. No server is left that is not terminated.
	2. No paid snapshot is left.
	3. No bucket subscription is still billing.
	4. No other add-on subscription is still billing, such as a public address.
	5. No invoice is unpaid.
	6. The current month's charges have a card to go to. Without an active payment method,
	   the month's draft would become an invoice that nobody can open or pay."""
	add_ons = _count_billing_add_ons(team)
	return [
		_get_check("servers", _count_live_servers(team)),
		_get_check("snapshots", add_ons["snapshots"]),
		_get_check("buckets", add_ons["buckets"]),
		_get_check("add_ons", add_ons["other"]),
		_get_check("invoices", _count_unpaid_invoices(team)),
		_get_check("final_bill", int(_has_current_charges(team) and not has_active_payment_method(team))),
	]


def get_archive_blockers(team: str) -> list[str]:
	"""Each failed check as a short phrase, for the error an operator or API caller reads."""
	labels = {
		"servers": _("{0} servers not terminated"),
		"snapshots": _("{0} paid snapshots"),
		"buckets": _("{0} buckets"),
		"add_ons": _("{0} other paid add-ons"),
		"invoices": _("{0} unpaid invoices"),
		"final_bill": _("a payment method for this month's charges"),
	}
	return [
		labels[check["key"]].format(check["count"])
		for check in get_archive_checks(team)
		if not check["passed"]
	]


def get_credit_balances(team: str) -> list[dict]:
	"""The credit the team still holds, per currency. Archiving forfeits it."""
	return frappe.get_all(
		"Credit Wallet", filters={"team": team, "balance": (">", 0)}, fields=["currency", "balance"]
	)


def _get_check(key: str, count: int) -> dict:
	return {"key": key, "passed": count == 0, "count": count}


def _count_live_servers(team: str) -> int:
	return frappe.db.count("Virtual Machine", {"team": team, "status": ("!=", "Terminated")})


def _count_billing_add_ons(team: str) -> dict[str, int]:
	# A server's own subscription closes with the server, so the servers check covers it.
	rows = frappe.get_all(
		"Subscription",
		filters={"team": team, "enabled": 1, "server_id": ("is", "not set")},
		fields=["vm_snapshot", "service_subject"],
	)
	snapshots = sum(1 for row in rows if row.vm_snapshot)
	buckets = sum(1 for row in rows if not row.vm_snapshot and row.service_subject)
	return {"snapshots": snapshots, "buckets": buckets, "other": len(rows) - snapshots - buckets}


def _count_unpaid_invoices(team: str) -> int:
	invoice = frappe.qb.DocType("Invoice")
	closed_month_draft = (invoice.status == "Draft") & (invoice.period_end < get_first_day(today()))
	return (
		frappe.qb.from_(invoice)
		.select(Count("*"))
		.where(
			(invoice.team == team)
			& (invoice.invoice_type == "Billable")
			& (invoice.status.isin(("Open", "Overdue")) | closed_month_draft)
		)
	).run()[0][0]


def _has_current_charges(team: str) -> bool:
	return bool(
		frappe.db.exists(
			"Invoice",
			{
				"team": team,
				"invoice_type": "Billable",
				"status": "Draft",
				"period_end": (">=", get_first_day(today())),
				"total": (">", 0),
			},
		)
	)
