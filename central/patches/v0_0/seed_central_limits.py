import frappe

DEFAULTS = {
	"invitations_per_hour": 50,
	"invitation_resend_cooldown_minutes": 5,
	"sign_in_code_attempts": 5,
	"sign_in_codes_per_email": 5,
	"trial_servers_per_team": 3,
}


def execute() -> None:
	"""Store today's limits on the existing Central Settings, so no limit reads as 0."""
	for fieldname, value in DEFAULTS.items():
		if not frappe.db.get_single_value("Central Settings", fieldname):
			frappe.db.set_single_value("Central Settings", fieldname, value)
