import frappe

from central.billing import settings
from central.billing.doctype.billing_event.billing_event import flow_of, outcome_of
from central.billing.doctype.billing_run_team.billing_run_team import FAILED, record_outcome
from central.billing.payments.provisioning import ensure_tax_profile


def execute() -> None:
	settings.ensure_minimum_invoice_amounts()
	name_flow_and_outcome_on_old_events()
	frappe.clear_document_cache("Billing Settings", "Billing Settings")
	add_missing_tax_profiles()
	queue_teams_the_last_run_missed()


def name_flow_and_outcome_on_old_events() -> None:
	for event in frappe.get_all(
		"Billing Event",
		filters={"category": ["is", "not set"]},
		fields=["name", "subject_doctype", "event_type", "to_state"],
	):
		values = {
			"category": flow_of(event.subject_doctype),
			"outcome": outcome_of(event.event_type, event.to_state),
		}
		frappe.db.set_value("Billing Event", event.name, values, update_modified=False)


def add_missing_tax_profiles() -> None:
	"""A team with no Tax Profile was billed with no tax."""
	internal = set(frappe.get_all("Billing Profile", filters={"is_internal": 1}, pluck="team"))
	taxed = set(frappe.get_all("Tax Profile", pluck="team"))
	for team in frappe.get_all("Billing Profile", pluck="team"):
		if team not in internal and team not in taxed:
			ensure_tax_profile(team)


def queue_teams_the_last_run_missed() -> None:
	"""A team the last run could not invoice has no record of it. Queue it for the hourly retry."""
	runs = frappe.get_all(
		"Billing Run", filters={"drafted": [">", 0]}, pluck="period_end", order_by="period_end desc", limit=1
	)
	if not runs:
		return
	invoiced = set(frappe.get_all("Invoice", filters={"period_end": runs[0]}, pluck="team"))
	for team in frappe.get_all("Subscription", pluck="team", distinct=True):
		if team not in invoiced:
			record_outcome(team, runs[0], FAILED, reason="Missed by the last billing run. Retrying.")
