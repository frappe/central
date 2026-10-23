import frappe

from central.central.doctype.app_rollout_hold.app_rollout_hold import AppRolloutHold

ALERT_ROLE = "App Rollout Alert"


@frappe.whitelist(methods=["POST"])
def hold_app_releases(context: dict) -> None:
	"""Hold the releases an Insights alert found failing. Insights signs in with an OAuth
	bearer token of a user that has only the App Rollout Alert role."""
	frappe.only_for(ALERT_ROLE)
	AppRolloutHold.hold_failing_releases(context.get("rows"))
