import frappe


def execute() -> None:
	"""Start the ladder that counts from the payment date: retry every 2 days, suspend on the
	15th, and alert an operator about termination 10 days after suspension."""
	frappe.db.set_single_value(
		"Billing Settings",
		{"dunning_retry_interval_days": 2, "suspension_day": 15, "terminate_after_days": 10},
	)
