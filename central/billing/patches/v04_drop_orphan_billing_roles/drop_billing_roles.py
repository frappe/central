# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Remove the orphan `Billing Admin` / `Billing User` roles (issue #44).

The old standalone app bootstrapped these two roles via an `after_migrate` shim
(`ensure_billing_roles`). #42 retired billing's own authz for Central's
capability IAM and deleted the shim, but a role already written to the database
cannot un-create itself by removing the hook — so on any site that migrated
while the shim existed the two roles linger with nothing referencing them.

This patch deletes them. By the time it runs nothing points at them: billing's
DocType JSONs carry no permissions for these roles, and #42 stripped every
`require_billing_admin` code path. Idempotent — a fresh Central never had them,
so the patch is a no-op there.
"""

import frappe

ORPHAN_ROLES = ("Billing Admin", "Billing User")


def execute() -> None:
	for role in ORPHAN_ROLES:
		if not frappe.db.exists("Role", role):
			continue

		# Defensive: drop any stray role assignments so delete_doc has no links
		# to choke on. There should be none after #42.
		frappe.db.delete("Has Role", {"role": role})
		frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
