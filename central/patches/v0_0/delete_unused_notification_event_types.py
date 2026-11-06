import frappe

UNUSED_EVENT_TYPES = ("mandate_reauth", "team_suspension", "server_suspension")


def execute() -> None:
	"""Delete the notification event types that no code sends.

	A fixture sync adds and updates event types, but it never deletes one that left the fixture."""
	frappe.db.delete("Notification Event Type", {"name": ["in", UNUSED_EVENT_TYPES]})
