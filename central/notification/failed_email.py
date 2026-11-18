import frappe

from central.iam import get_active_team_member_users


def email_admins_when_owner_email_fails(log, method=None) -> None:
	"""Send a critical event to the team's Admins when Frappe gives up on the owner's email."""
	if log.document_type != "Email Queue":
		return
	notification = frappe.db.get_value(
		"Email Queue", {"name": log.document_name, "reference_doctype": "Team Notification"}, "reference_name"
	)
	row = notification and frappe.db.get_value(
		"Team Notification", notification, ["team", "event_type", "template_context"], as_dict=True
	)
	if not row or not frappe.db.get_value("Notification Event Type", row.event_type, "is_critical"):
		return

	owner = frappe.db.get_value("Team", row.team, "owner_user")
	if not frappe.db.exists("Email Queue Recipient", {"parent": log.document_name, "recipient": owner}):
		return

	frappe.log_error(title=f"Critical notification email to team owner failed: {row.team} {row.event_type}")
	admins = get_active_team_member_users(row.team, role="Admin")
	if admins:
		frappe.enqueue(
			"central.notification.engine.send_notification_emails",
			queue="short",
			enqueue_after_commit=True,
			recipients=admins,
			event_type=row.event_type,
			ctx=frappe.parse_json(row.template_context),
		)
