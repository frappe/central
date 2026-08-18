# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Strip the capability catalog to model v3 (CAPABILITY_VERSION 3).

v3 makes the server the atomic unit: role capabilities live at the team and
server level only. The bench plane (every `site:*` cap plus `server:config`) and
the redundant `asset:view` (the Asset registry is gated on `server:view`) are
dropped, and the system roles collapse from eight back to five — Operator, Site
Manager and Support only existed to slice the now-removed site granularity.

Fixture sync never deletes records, so without this patch the removed capabilities
would linger in the role-builder palette, the retired roles would survive, and any
member still on a retired role would dangle (its role no longer resolves, and the
team would fail to save). Runs in post_model_sync, BEFORE sync_fixtures, so the new
fixtures have not landed yet — we work at the DB level only. Idempotent: once the
strip has run the removed names and roles match nothing.
"""

import frappe

# Dropped capabilities: the whole bench plane + the redundant asset:view.
REMOVED_CAPABILITIES = (
	"asset:view",
	"server:config",
	"site:apps",
	"site:backup",
	"site:config",
	"site:console",
	"site:create",
	"site:db",
	"site:delete",
	"site:logs",
	"site:migrate",
	"site:restore",
	"site:view",
)

# Retired system roles -> the surviving role members are moved to. Operator and
# Site Manager were server/site operators -> Developer; Support was read-only ->
# Viewer.
RETIRED_ROLES = {
	"Operator": "Developer",
	"Site Manager": "Developer",
	"Support": "Viewer",
}


def execute() -> None:
	_reassign_retired_role_members()
	_delete_retired_roles()
	_drop_removed_capability_grants()
	_drop_removed_permission_probes()
	_drop_removed_capabilities()


def _reassign_retired_role_members() -> None:
	"""Move every member on a retired role onto its successor before the role goes,
	so the membership keeps resolving and the team still saves."""
	for retired, successor in RETIRED_ROLES.items():
		frappe.db.set_value("Team Member", {"role": retired}, "role", successor, update_modified=False)


def _delete_retired_roles() -> None:
	"""Delete the retired Team Role docs and their Role Capability children at the DB
	level (Team Role.on_trash forbids deleting a system role, so no delete_doc)."""
	for retired in RETIRED_ROLES:
		frappe.db.delete("Role Capability", {"parenttype": "Team Role", "parent": retired})
		frappe.db.delete("Team Role", {"name": retired})


def _drop_removed_capability_grants() -> None:
	"""Drop Role Capability rows that grant a removed capability — on system roles
	(sync_fixtures rewrites those anyway) and any team-defined custom role."""
	for capability in REMOVED_CAPABILITIES:
		frappe.db.delete("Role Capability", {"capability": capability})


def _drop_removed_permission_probes() -> None:
	"""IAM Permission Probe stores one capability to evaluate; drop probes pinned to
	a removed one so the palette and diagnostics stay consistent."""
	if not frappe.db.has_table("IAM Permission Probe"):
		return
	for capability in REMOVED_CAPABILITIES:
		frappe.db.delete("IAM Permission Probe", {"capability": capability})


def _drop_removed_capabilities() -> None:
	"""Delete the retired Capability docs. Every stored reference was dropped above,
	and the surviving names arrive via sync_fixtures."""
	for capability in REMOVED_CAPABILITIES:
		frappe.db.delete("Capability", {"name": capability})
