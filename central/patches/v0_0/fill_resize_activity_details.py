import frappe

from central.central.doctype.activity_event.activity_event import clear_feed_cache, get_action_details


def execute() -> None:
	"""Fill the plan and size on past resize events from the Resource Action each one names."""
	events = frappe.get_all(
		"Activity Event",
		filters={"event": "server.resized", "reference_doctype": "Resource Action"},
		fields=["name", "team", "reference_name"],
	)
	actions = {
		row.name: frappe.get_doc({"doctype": "Resource Action", **row})
		for row in frappe.get_all(
			"Resource Action",
			filters={"name": ("in", [event.reference_name for event in events])},
			fields=["name", "action", "status", "request_payload"],
		)
	}
	for event in events:
		if action := actions.get(event.reference_name):
			details = get_action_details(action)
			value = frappe.as_json(details) if details else None
			frappe.db.set_value("Activity Event", event.name, "details", value, update_modified=False)

	for team in {event.team for event in events}:
		clear_feed_cache(team)
