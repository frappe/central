# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Post-sync guard for the team→Team migration (issue #43).

Runs **post_model_sync** — after `team` is a `Link → Team` — and fails the
migrate if anything slipped: a `team` value that points at no real `Team`, or a
field that didn't flip to Link. Cheap insurance that cutover left billing's data
fully linked.
"""

import frappe

from central.billing.patches.v03_team_link_to_central_team.migrate_team_to_central_team import (
	TEAM_DOCTYPES,
)


def execute() -> None:
	for doctype in TEAM_DOCTYPES:
		field = frappe.get_meta(doctype).get_field("team")
		if field.fieldtype != "Link" or field.options != "Team":
			frappe.throw(f"{doctype}.team is not a Link → Team (got {field.fieldtype}).")

		orphans = frappe.db.sql(
			f"""
			SELECT DISTINCT child.team
			FROM `tab{doctype}` child
			LEFT JOIN `tabTeam` team ON team.name = child.team
			WHERE child.team IS NOT NULL AND child.team != '' AND team.name IS NULL
			"""
		)
		if orphans:
			frappe.throw(
				f"{doctype} has {len(orphans)} team value(s) linking to no Team: "
				f"{[row[0] for row in orphans]}"
			)
