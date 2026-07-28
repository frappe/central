# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Migrate the capability catalog to model v2 (CAPABILITY_VERSION 2).

v2 collapses the user-facing vocabulary to two namespaces — `server:*` (one VM =
one bench, so the old atlas `vm:*` and bench `bench:*` caps merge) and `site:*`
(the orphan `app:install`/`db:access`/`log:view`/`task:run` caps move under it).
The updated fixtures add the new Capability docs and rewrite the system roles, but
fixture sync never deletes records — so without this patch every renamed cap would
linger as an orphan in the catalog (polluting the role-builder palette) and any
stored grant referencing an old name would dangle.

Runs in post_model_sync, i.e. BEFORE sync_fixtures, so the new Capability docs may
not exist yet. We therefore work at the DB level only: rewrite the capability value
on every stored grant (Role Capability child rows + IAM Permission Probe), dedupe
the rows that two old caps now collapse into, then delete the orphan Capability
docs. Idempotent: once the rename has run the old names match nothing.
"""

import frappe

# old name -> new name. Several old caps merge into one (vm:start + vm:stop ->
# server:power, etc.); the dedupe step below collapses the resulting duplicates.
RENAME = {
	"vm:view": "server:view",
	"vm:open": "server:open",
	"vm:create": "server:create",
	"vm:terminate": "server:terminate",
	"vm:start": "server:power",
	"vm:stop": "server:power",
	"vm:resize": "server:resize",
	"vm:rebuild": "server:resize",
	"vm:snapshot": "server:snapshot",
	"bench:config": "server:config",
	"bench:manage": "server:config",
	"app:install": "site:apps",
	"db:access": "site:db",
	"log:view": "site:logs",
	"task:run": "site:console",
}


def execute() -> None:
	_rename_role_capabilities()
	_rename_permission_probes()
	_drop_orphan_capabilities()


def _rename_role_capabilities() -> None:
	"""Rewrite Role Capability child rows in place, then drop the duplicates that a
	merge (e.g. vm:start + vm:stop -> server:power) leaves behind on one parent."""
	for old, new in RENAME.items():
		frappe.db.set_value("Role Capability", {"capability": old}, "capability", new, update_modified=False)

	rows = frappe.get_all(
		"Role Capability",
		filters={"parenttype": "Team Role"},
		fields=["name", "parent", "capability", "idx"],
		order_by="parent, idx",
	)
	seen: set[tuple[str, str]] = set()
	for row in rows:
		key = (row.parent, row.capability)
		if key in seen:
			frappe.db.delete("Role Capability", {"name": row.name})
		else:
			seen.add(key)


def _rename_permission_probes() -> None:
	"""IAM Permission Probe stores a single capability to evaluate — keep it valid."""
	if not frappe.db.has_table("IAM Permission Probe"):
		return
	for old, new in RENAME.items():
		frappe.db.set_value(
			"IAM Permission Probe", {"capability": old}, "capability", new, update_modified=False
		)


def _drop_orphan_capabilities() -> None:
	"""Delete the renamed-away Capability docs. Direct delete (no link scan) — every
	stored reference was rewritten above, and the new names arrive via sync_fixtures."""
	for old in RENAME:
		frappe.db.delete("Capability", {"name": old})
