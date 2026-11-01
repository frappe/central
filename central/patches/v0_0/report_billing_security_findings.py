import json

import frappe

SHAPE_ROWS = ("Compute", "Memory", "Disk", "Transfer")
LISTED = 50  # names per check in the report; the counts are complete


def execute() -> None:
	"""Report, without changing anything, the data the billing security fixes of October 2026
	would have refused. An operator decides each correction."""
	checks = {
		"negative_locked_rates": _negative_locked_rates(),
		"server_shapes_with_extra_or_negative_rows": _bad_shapes(),
		"services_on_retired_plans": _services_on_retired_plans(),
		"india_teams_without_gst": _india_teams_without_gst(),
		"invoices_paid_for_less_than_due": _short_paid_invoices(),
	}
	found = {name: {"count": len(rows), "first": rows[:LISTED]} for name, rows in checks.items() if rows}
	if found:
		frappe.log_error(
			title="Billing security review: data to check", message=json.dumps(found, indent=1, default=str)
		)


def _negative_locked_rates() -> list:
	return frappe.get_all("Subscription Change", filters={"locked_rate": ["<", 0]}, pluck="subscription")


def _bad_shapes() -> list:
	rows = frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Subscription"},
		fields=["parent", "resource_type", "quantity"],
	)
	servers = set(
		frappe.get_all(
			"Subscription", filters={"server_id": ["is", "set"], "pricing_mode": "Composed"}, pluck="name"
		)
	)
	return sorted(
		{
			r.parent
			for r in rows
			if r.parent in servers
			and (r.resource_type not in SHAPE_ROWS or frappe.utils.flt(r.quantity) <= 0)
		}
	)


def _services_on_retired_plans() -> list:
	retired = set(frappe.get_all("Plan", filters={"is_active": 0}, pluck="name"))
	return [
		s.name
		for s in frappe.get_all(
			"Subscription", filters={"service_subject": ["is", "set"], "enabled": 1}, fields=["name", "plan"]
		)
		if s.plan in retired
	]


def _india_teams_without_gst() -> list:
	india = frappe.get_all(
		"Billing Profile", filters=[["country", "=", "India"]], pluck="team"
	) + frappe.get_all("Billing Profile", filters={"currency": "INR"}, pluck="team")
	untaxed = frappe.get_all(
		"Tax Profile",
		filters={
			"team": ["in", list(set(india)) or [""]],
			"output_tax_type": ["!=", "GST"],
			"is_internal": 0,
			"zero_rated": 0,
		},
		pluck="team",
	)
	return sorted(untaxed)


def _short_paid_invoices() -> list:
	return [
		i.name
		for i in frappe.get_all(
			"Invoice",
			filters={"status": "Paid", "amount_paid": [">", 0]},
			fields=["name", "amount_paid", "expected_collection"],
		)
		if frappe.utils.flt(i.amount_paid) + 0.005 < frappe.utils.flt(i.expected_collection)
	]
