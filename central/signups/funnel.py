import frappe
from frappe.utils.telemetry import capture


def capture_trial_event(
	event: str, team: str, product: str | None, user: str | None = None, **properties
) -> None:
	"""Send one trial step to the Pulse signup funnel under the customer's team, once the step
	commits. A step that rolls back sends nothing. The user defaults to the team owner."""
	user = user or frappe.get_cached_value("Team", team, "owner_user")
	frappe.db.after_commit.add(
		lambda: capture(event, "central", user=user, team=team, properties={"product": product, **properties})
	)
