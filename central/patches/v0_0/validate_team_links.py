# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Post-sync guard for the team→Team migration (issue #43).

Runs **post_model_sync** — after `team` is a `Link → Team` — and fails the
migrate if anything slipped: a `team` value that points at no real `Team`, or a
field that didn't flip to Link. Cheap insurance that cutover left billing's data
fully linked.
"""

import frappe
from frappe import _

from central.patches.v0_0.migrate_team_to_central_team import (
	TEAM_DOCTYPES,
)


def execute() -> None:
	for doctype in TEAM_DOCTYPES:
		field = frappe.get_meta(doctype).get_field("team")
		if field.fieldtype != "Link" or field.options != "Team":
			frappe.throw(_("{0}.team is not a Link → Team (got {1}).").format(doctype, field.fieldtype))

		child = frappe.qb.DocType(doctype)
		team = frappe.qb.DocType("Team")
		orphans = (
			frappe.qb.from_(child)
			.left_join(team)
			.on(team.name == child.team)
			.select(child.team)
			.distinct()
			.where(child.team.isnotnull() & (child.team != "") & team.name.isnull())
			.run(pluck=True)
		)
		if orphans:
			frappe.throw(_("{0} has {1} team value(s) linking to no Team: {2}").format(doctype, len(orphans), orphans))
