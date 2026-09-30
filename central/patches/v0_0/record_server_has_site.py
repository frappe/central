import frappe


def execute() -> None:
	"""Backfill `has_site`, then remove Sites on servers whose image has none."""
	for action in frappe.get_all(
		"Resource Action",
		filters={"action": "create", "server": ["is", "set"]},
		fields=["server", "resource_type", "request_payload"],
	):
		if _carries_a_site(action):
			frappe.db.set_value("Virtual Machine", action.server, "has_site", 1, update_modified=False)

	servers_without_a_site = frappe.get_all("Virtual Machine", filters={"has_site": 0}, pluck="name")
	if not servers_without_a_site:
		return

	for site in frappe.get_all("Site", filters={"server": ["in", servers_without_a_site]}, pluck="name"):
		frappe.delete_doc("Site", site, ignore_permissions=True)


def _carries_a_site(action: frappe._dict) -> bool:
	# A trial always boots a site image.
	if action.resource_type == "Site":
		return True

	tags = (frappe.parse_json(action.request_payload or "{}") or {}).get("image_tags") or {}
	return tags.get("has_site") == "1"
