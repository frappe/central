import frappe

DEFAULTS = {
	"app_rollout_start_percent": 5,
	"app_rollout_step_percent": 5,
	"app_rollout_interval_hours": 8,
	"app_rollout_max_percent": 100,
	"app_rollout_failure_percent": 20,
	"app_rollout_minimum_servers": 5,
}


def execute() -> None:
	"""Store the app rollout steps on the existing Central Settings, so none reads as 0."""
	for fieldname, value in DEFAULTS.items():
		if not frappe.db.get_single_value("Central Settings", fieldname):
			frappe.db.set_single_value("Central Settings", fieldname, value)
