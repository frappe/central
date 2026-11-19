import frappe


def execute() -> None:
	"""Mark the site creations that started a free trial. A recorded site was a trial when it got an end date. An unrecorded one is a trial when its team still has no payment method."""
	trial_servers = frappe.get_all("Site", filters={"trial_ends_on": ["is", "set"]}, pluck="server")
	recorded = set(frappe.get_all("Site", filters={"server": ["is", "set"]}, pluck="server"))
	paying = set(frappe.get_all("Payment Method", filters={"status": "Active"}, pluck="team", distinct=True))
	creations = frappe.get_all(
		"Resource Action",
		filters={"action": "create", "resource_type": "Site"},
		fields=["name", "server", "team"],
	)
	unrecorded = [
		creation.name
		for creation in creations
		if creation.server not in recorded and creation.team not in paying
	]
	if trial_servers:
		mark({"server": ["in", trial_servers]})
	if unrecorded:
		mark({"name": ["in", unrecorded]})


def mark(filters: dict) -> None:
	frappe.db.set_value(
		"Resource Action",
		{"action": "create", "resource_type": "Site", **filters},
		"is_free_trial",
		1,
		update_modified=False,
	)
