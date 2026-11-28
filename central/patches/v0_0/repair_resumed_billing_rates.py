import frappe

# What the pause code wrote before it carried the rate: a Resumed row with the enabled flag as its value.
OLD_RESUME = {"change_type": "Resumed", "new_value": "1", "locked_rate": 0}
RATED = ("Created", "Plan Changed", "Resumed")


def execute():
	"""Give each server resumed before the fix the rate it had before its pause.

	Until then a resume opened its segment at 0, so the server billed nothing from the day it was resumed."""
	# Oldest first, so a second resume of the same server reads the rate the first one was given.
	resumed_rows = frappe.get_all(
		"Subscription Change",
		filters=OLD_RESUME,
		fields=["name", "subscription", "effective_at"],
		order_by="effective_at asc",
	)
	for resumed in resumed_rows:
		before = rate_before(resumed)
		if before:
			frappe.db.set_value("Subscription Change", resumed.name, before, update_modified=False)


def rate_before(resumed) -> dict | None:
	"""The rate, currency, label and resources of the last rated change before the resume."""
	changes = frappe.get_all(
		"Subscription Change",
		filters={
			"subscription": resumed.subscription,
			"change_type": ["in", RATED],
			"effective_at": ["<", resumed.effective_at],
			"name": ["!=", resumed.name],
		},
		fields=["locked_rate", "currency", "new_value", "included_resources"],
		order_by="effective_at desc, creation desc",
		limit=1,
	)
	return changes[0] if changes else None
