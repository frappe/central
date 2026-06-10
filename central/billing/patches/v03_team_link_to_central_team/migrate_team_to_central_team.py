# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Re-point billing's `team` from a free-text `Data` slug to the real Central
`Team` (issue #43, ADR 0004 §4).

Runs **pre_model_sync** — while `team` is still a `Data` column on all 16 billing
tables — so we can ensure a `Team` per legacy slug, rewrite every value to the
`Team.name`, and rename the five `field:team`-named docs (Credit Wallet, Trust
Tier, Tax Profile, Billing Profile, Notification Preference) so their `name`
still equals `team`. The field-type flip to `Link → Team` then lands on values
that are already valid links.

Access continuity is part of the migration, not a follow-up: every user who
could reach a team's billing under the old model (`User.billing_team`) becomes
an Active `Team Member` with a billing-capable role on the matching `Team`.
The legacy `User.billing_team` Custom Field is then dropped — billing carries no
field of its own on `User`; the `team` link is the sole identity.

Idempotent and re-runnable: a value that is already a `Team.name` is left alone.
"""

from collections import Counter, defaultdict

import frappe
from frappe.model.rename_doc import rename_doc

# The 16 billing DocTypes carrying `team` (Notification Log was renamed to
# Billing Notification Log in #41).
TEAM_DOCTYPES = [
	"Subscription",
	"Invoice",
	"Price Lock",
	"Credit Wallet",
	"Credit Ledger Entry",
	"Payment Method",
	"Payment Attempt",
	"Refund",
	"Commitment",
	"Usage Rollup",
	"Tax Profile",
	"Billing Profile",
	"Entitlement Token",
	"Trust Tier",
	"Billing Notification Log",
	"Notification Preference",
]

# Of those, the ones autonamed `field:team` — their document `name` *is* the
# team value, and code looks them up by name (e.g. `get_doc("Trust Tier", team)`).
# Renaming keeps the `name == team` invariant after the slug→Team.name rewrite.
FIELD_TEAM_DOCTYPES = [
	"Credit Wallet",
	"Trust Tier",
	"Tax Profile",
	"Billing Profile",
	"Notification Preference",
]

MEMBER_ROLE = "Billing"  # carries billing:view + billing:manage


def execute() -> None:
	legacy_access = _legacy_billing_access()
	slugs = _distinct_team_slugs() | set(legacy_access)
	if not slugs:
		_drop_billing_team_field()
		return

	mapping = {slug: _ensure_team(slug, legacy_access.get(slug, [])) for slug in slugs}

	before = _snapshot_team_counts()
	_rewrite_team_values(mapping)
	_rename_field_team_docs(mapping)
	_assert_round_trip(before, mapping)

	_drop_billing_team_field()
	frappe.db.commit()


# --- discovery --------------------------------------------------------------


def _distinct_team_slugs() -> set[str]:
	"""Every non-empty `team` value across the 16 tables (raw SQL — still Data)."""
	slugs: set[str] = set()
	for doctype in TEAM_DOCTYPES:
		rows = frappe.db.sql(
			f"SELECT DISTINCT team FROM `tab{doctype}` WHERE team IS NOT NULL AND team != ''"
		)
		slugs.update(row[0] for row in rows)
	return slugs


def _legacy_billing_access() -> dict[str, list[str]]:
	"""slug → users who had billing access via the old `User.billing_team` field.

	The field is dropped by this patch; we read it first so access survives
	cutover. Empty if the field is already gone (re-run / fresh site)."""
	if not _billing_team_column_exists():
		return {}
	access: dict[str, list[str]] = defaultdict(list)
	rows = frappe.db.sql(
		"SELECT name, billing_team FROM `tabUser` "
		"WHERE billing_team IS NOT NULL AND billing_team != ''",
		as_dict=True,
	)
	for row in rows:
		access[row.billing_team].append(row.name)
	return dict(access)


def _billing_team_column_exists() -> bool:
	return "billing_team" in frappe.db.get_table_columns("User")


# --- team creation + member backfill ---------------------------------------


def _ensure_team(slug: str, member_users: list[str]) -> str:
	"""The `Team.name` for a legacy slug — an existing team, or a freshly created
	one named after the slug. Backfills legacy billing users as Active members so
	they keep access under capability IAM (#42)."""
	if frappe.db.exists("Team", slug):
		# Already a Team.name — a prior run, or a slug that was always the real id.
		_ensure_members(slug, member_users)
		return slug

	existing = frappe.db.get_value("Team", {"team_name": slug}, "name")
	if existing:
		_ensure_members(existing, member_users)
		return existing

	owner = member_users[0] if member_users else "Administrator"
	others = [u for u in member_users if u != owner]
	team = frappe.get_doc(
		{
			"doctype": "Team",
			"team_name": slug,
			"owner_user": owner,
			"members": [
				{"user": u, "role": MEMBER_ROLE, "status": "Active"} for u in others
			],
		}
	).insert(ignore_permissions=True)
	return team.name


def _ensure_members(team_name: str, member_users: list[str]) -> None:
	"""Idempotently make each legacy user an Active billing member of `team_name`."""
	if not member_users:
		return
	team = frappe.get_doc("Team", team_name)
	present = {m.user for m in team.members}
	added = False
	for user in member_users:
		if user in present:
			continue
		team.append("members", {"user": user, "role": MEMBER_ROLE, "status": "Active"})
		added = True
	if added:
		team.save(ignore_permissions=True)


# --- rewrite + rename -------------------------------------------------------


def _snapshot_team_counts() -> dict[str, Counter]:
	"""Per-doctype histogram of `team` values, taken before the rewrite, for the
	round-trip proof that no row changes team ownership."""
	snapshot: dict[str, Counter] = {}
	for doctype in TEAM_DOCTYPES:
		rows = frappe.db.sql(
			f"SELECT team FROM `tab{doctype}` WHERE team IS NOT NULL AND team != ''"
		)
		snapshot[doctype] = Counter(row[0] for row in rows)
	return snapshot


def _rewrite_team_values(mapping: dict[str, str]) -> None:
	"""Slug → Team.name on every table (raw SQL, before the Link constraint)."""
	for doctype in TEAM_DOCTYPES:
		for slug, team_name in mapping.items():
			if slug == team_name:
				continue
			frappe.db.sql(
				f"UPDATE `tab{doctype}` SET team = %s WHERE team = %s", (team_name, slug)
			)


def _rename_field_team_docs(mapping: dict[str, str]) -> None:
	"""Rename `field:team`-named docs slug→Team.name so `name == team` holds."""
	for doctype in FIELD_TEAM_DOCTYPES:
		for slug, team_name in mapping.items():
			if slug == team_name:
				continue
			if frappe.db.exists(doctype, slug) and not frappe.db.exists(doctype, team_name):
				rename_doc(
					doctype,
					slug,
					team_name,
					force=True,
					ignore_permissions=True,
					show_alert=False,
				)


def _assert_round_trip(before: dict[str, Counter], mapping: dict[str, str]) -> None:
	"""Prove no row lost or changed team ownership: the mapped before-histogram
	must equal the after-histogram, per doctype."""
	for doctype in TEAM_DOCTYPES:
		expected: Counter = Counter()
		for slug, count in before[doctype].items():
			expected[mapping[slug]] += count
		actual = Counter(
			row[0]
			for row in frappe.db.sql(
				f"SELECT team FROM `tab{doctype}` WHERE team IS NOT NULL AND team != ''"
			)
		)
		if expected != actual:
			frappe.throw(
				f"Team migration round-trip mismatch on {doctype}: "
				f"expected {dict(expected)}, got {dict(actual)}"
			)


# --- legacy field removal ---------------------------------------------------


def _drop_billing_team_field() -> None:
	"""Remove the legacy `User.billing_team` Custom Field *and* its column — billing
	keeps no field of its own on User; the `team` link is the identity. Frappe does
	not auto-drop orphaned columns, so the DDL is explicit."""
	if frappe.db.exists("Custom Field", "User-billing_team"):
		frappe.delete_doc(
			"Custom Field", "User-billing_team", force=True, ignore_permissions=True
		)
	if "billing_team" in frappe.db.get_table_columns("User"):
		# IF EXISTS so a stale column cache can't make a re-run error.
		frappe.db.sql_ddl("ALTER TABLE `tabUser` DROP COLUMN IF EXISTS `billing_team`")
