import frappe
from frappe.model.naming import make_autoname


def execute():
	"""`Team Role.autoname` was `format:TEAM-ROLE-.#####`, which the `format:` handler
	does not expand (it substitutes only brace-delimited params), so the first custom
	role on a site was named the literal string `TEAM-ROLE-.#####` and the second raised
	DuplicateEntryError. The JSON is fixed to `format:TEAM-ROLE-{#####}`; rename the one
	stale row so its links repoint and the series stays consistent with new inserts."""
	stale = "TEAM-ROLE-.#####"
	if not frappe.db.exists("Team Role", stale):
		return

	# Same "TEAM-ROLE-" series the corrected format autoname draws from, so no collision.
	new_name = make_autoname("TEAM-ROLE-.#####")
	frappe.rename_doc("Team Role", stale, new_name, force=True)
