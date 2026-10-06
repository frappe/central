import frappe


def execute() -> None:
	"""Backfill `has_site`, then remove Sites on servers whose image is known to have none.

	A server with no creation request that names its image keeps its Site: the Site
	record is the only evidence left, and it says the image carries one.
	"""
	bench_only = set()
	for action in frappe.get_all(
		"Resource Action",
		filters={"action": "create", "server": ["is", "set"]},
		fields=["server", "resource_type", "request_payload"],
	):
		has_site = _image_has_site(action)
		if has_site:
			frappe.db.set_value("Virtual Machine", action.server, "has_site", 1, update_modified=False)
		elif has_site is False:
			bench_only.add(action.server)

	servers_without_a_site = frappe.get_all("Virtual Machine", filters={"has_site": 0}, pluck="name")
	if not servers_without_a_site:
		return

	for site in frappe.get_all(
		"Site", filters={"server": ["in", servers_without_a_site]}, fields=["name", "server"]
	):
		if site.server in bench_only:
			_remove_site(site.name)
		else:
			frappe.db.set_value("Virtual Machine", site.server, "has_site", 1, update_modified=False)


def _image_has_site(action: frappe._dict) -> bool | None:
	"""Whether the requested image carries a site, or None when the request does not say."""
	# A trial always boots a site image.
	if action.resource_type == "Site":
		return True

	tags = (frappe.parse_json(action.request_payload or "{}") or {}).get("image_tags") or {}
	return {"1": True, "0": False}.get(tags.get("has_site"))


def _remove_site(site: str) -> None:
	# A Site Domain routes to the server, not the site, so it stays and only loses the link.
	frappe.db.set_value("Site Domain", {"site": site}, "site", None, update_modified=False)
	frappe.delete_doc("Site", site, ignore_permissions=True)
