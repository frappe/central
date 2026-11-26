import frappe

from central.notification.engine import queue_event


def notify(deploy_app: str, event_type: str, message: str = "") -> None:
	"""Tell the app's team, on the feed of the app's VM."""
	app = frappe.db.get_value(
		"Deploy App", deploy_app, ["team", "repository", "virtual_machine"], as_dict=True
	)
	queue_event(
		app.team,
		event_type,
		message=message,
		context={"app": app.repository},
		reference_doctype="Virtual Machine" if app.virtual_machine else None,
		reference_name=app.virtual_machine,
	)
