import frappe

# Overrides of the old ladder that the Billing Scenario DocType no longer has. Frappe keeps a
# removed field's column, so a value left there would come back if the field returned.
RETIRED_COLUMNS = {"dunning_retry_days": None, "suspend_after_days": 0}


def execute() -> None:
	"""Clear the old ladder overrides on every saved scenario.

	Terminate After counted from the due date before. It counts from suspension now, so an
	old value means something else. A cleared value reads the live setting."""
	scenario = frappe.qb.DocType("Billing Scenario")
	query = frappe.qb.update(scenario).set(scenario.terminate_after_days, 0)
	for column, cleared in RETIRED_COLUMNS.items():
		if frappe.db.has_column("Billing Scenario", column):
			query = query.set(scenario[column], cleared)
	query.run()
