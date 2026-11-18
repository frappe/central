import frappe

from central.central.doctype.app_rollout_hold.app_rollout_hold import AppRolloutHold
from central.iam import APP_ROLLOUT_ALERT_ROLE


@frappe.whitelist(methods=["POST"])
def hold_app_releases(context: dict) -> None:
	"""Hold the releases an Insights alert found failing. Insights signs in with an OAuth
	bearer token of a user that has only the App Rollout Alert role."""
	frappe.only_for(APP_ROLLOUT_ALERT_ROLE)
	AppRolloutHold.hold_failing_releases(context.get("rows"))
