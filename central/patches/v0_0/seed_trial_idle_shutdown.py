import frappe

DEFAULT_MINUTES = 30


def execute():
	"""Give an existing site the trial idle shutdown its new field defaults to.

	A field default applies when the Single document is first created, so a site that
	already had Central Settings reads the new field as unset. Unset and a deliberate
	zero look the same to the reader, and zero means "never sleep", so the value is
	written once here rather than guessed at every read."""
	if frappe.db.get_single_value("Central Settings", "trial_idle_shutdown_minutes"):
		return

	frappe.db.set_single_value("Central Settings", "trial_idle_shutdown_minutes", DEFAULT_MINUTES)
