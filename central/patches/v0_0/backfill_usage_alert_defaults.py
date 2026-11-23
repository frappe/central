import frappe


def execute():
	"""Send the default usage alerts to every live server that has them all off. The job calls each
	Pilot, so migrate does not wait on a server that is down."""
	frappe.enqueue(
		"central.integrations.pilot.backfill_usage_alert_defaults", queue="long", enqueue_after_commit=True
	)
