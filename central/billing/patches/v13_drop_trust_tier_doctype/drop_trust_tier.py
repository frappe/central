# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The per-team Trust Tier doctype folds into the Billing Profile (issue #62).

Each team already has exactly one Billing Profile, so a second per-team
singleton that snapshotted the tier's caps was redundant (and drifted). Copy
each Trust Tier's level link + audit onto the team's profile, preserve any
off-ladder manual cap as `override_max_spend`, then drop the doctype. Caps now
resolve live from the level × the team's currency (entitlements.get_team_caps).

Idempotent: once the table is dropped a re-run is a no-op.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Trust Tier"):
		return

	orphans = []
	for tt in frappe.get_all(
		"Trust Tier",
		fields=[
			"name", "team", "level", "tier", "manual_override",
			"max_spend", "promoted_at", "promotion_basis",
		],
	):
		team = tt.team or tt.name
		if not frappe.db.exists("Billing Profile", team):
			orphans.append(team)  # both are per-team singletons — shouldn't happen
			continue
		updates = {
			"trust_tier_level": tt.level,
			"trust_tier": tt.tier,
			"manual_override": tt.manual_override,
			"promoted_at": tt.promoted_at,
			"promotion_basis": tt.promotion_basis,
		}
		# A manually pinned, off-ladder cap is kept as a bespoke override; an
		# auto-tier's cap re-resolves from the level, so it isn't carried.
		if tt.manual_override and tt.max_spend:
			updates["override_max_spend"] = tt.max_spend
		frappe.db.set_value("Billing Profile", team, updates, update_modified=False)

	if orphans:
		frappe.logger("migrate").warning(
			f"v13_drop_trust_tier: {len(orphans)} Trust Tier rows had no Billing Profile "
			f"and were dropped without migration: {orphans}"
		)

	frappe.delete_doc("DocType", "Trust Tier", force=True, ignore_missing=True)
	# delete_doc removes the doctype metadata but not always the physical table —
	# drop it explicitly so no orphan `tabTrust Tier` lingers.
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabTrust Tier`")
