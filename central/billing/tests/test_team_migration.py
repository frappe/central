# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Round-trip proof for the team→Team migration (issue #43, ADR 0004 §4).

The live `bench migrate` exercised the plain-rewrite path on real Subscription /
Invoice data. This proves the two paths that need a populated table to show:
the `field:team` rename (so `name == team` survives) and re-runnability — by
planting a legacy `Data` slug via raw SQL (simulating un-migrated data) and
running the patch helpers, then running them again.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.patches.v03_team_link_to_central_team import (
	migrate_team_to_central_team as patch,
)
from central.billing.tests.utils import make_billing_team, make_user

def _run_migration():
	"""execute() minus the commit + field drop, so the test stays transactional."""
	legacy = patch._legacy_billing_access()
	slugs = patch._distinct_team_slugs() | set(legacy)
	mapping = {s: patch._ensure_team(s, legacy.get(s, [])) for s in slugs}
	before = patch._snapshot_team_counts()
	patch._rewrite_team_values(mapping)
	patch._rename_field_team_docs(mapping)
	patch._assert_round_trip(before, mapping)
	return mapping


class TestTeamMigration(IntegrationTestCase):
	def setUp(self):
		# Unique slug per test — rename_doc commits, so a fixed name would bleed
		# across methods.
		self.slug = f"legacy-mig-{frappe.generate_hash(6)}"
		# A real Team to hang valid docs off, then demote them to a legacy slug.
		real_team = make_billing_team(make_user()).name
		sub = frappe.get_doc({"doctype": "Subscription", "team": real_team}).insert(
			ignore_permissions=True
		)
		frappe.get_doc({"doctype": "Trust Tier", "team": real_team}).insert(
			ignore_permissions=True
		)  # field:team → name == real_team

		# Plant un-migrated state: a free-text slug on both the plain row and the
		# field:team-named row (its `name` is the slug too).
		frappe.db.sql(
			"UPDATE `tabSubscription` SET team = %s WHERE name = %s", (self.slug, sub.name)
		)
		frappe.db.sql(
			"UPDATE `tabTrust Tier` SET name = %s, team = %s WHERE name = %s",
			(self.slug, self.slug, real_team),
		)
		self.sub = sub.name

	def test_slug_is_repointed_to_a_real_team(self):
		_run_migration()

		team_name = frappe.db.get_value("Team", {"team_name": self.slug}, "name")
		self.assertTrue(team_name, "a Team should be created for the legacy slug")
		self.assertEqual(frappe.db.get_value("Subscription", self.sub, "team"), team_name)

	def test_field_team_doc_is_renamed_so_name_equals_team(self):
		_run_migration()
		team_name = frappe.db.get_value("Team", {"team_name": self.slug}, "name")

		self.assertFalse(
			frappe.db.exists("Trust Tier", self.slug), "slug-named tier should be gone"
		)
		self.assertTrue(frappe.db.exists("Trust Tier", team_name))
		# the invariant code relies on: get_doc("Trust Tier", team) still works.
		self.assertEqual(frappe.db.get_value("Trust Tier", team_name, "team"), team_name)

	def test_migration_is_idempotent(self):
		_run_migration()
		first = frappe.db.get_value("Team", {"team_name": self.slug}, "name")

		_run_migration()  # must not throw, nor create a second team
		teams = frappe.get_all("Team", filters={"team_name": self.slug}, pluck="name")
		self.assertEqual(teams, [first])
		self.assertEqual(frappe.db.get_value("Subscription", self.sub, "team"), first)

	def test_distinct_slugs_keep_distinct_ownership(self):
		"""Two un-migrated rows on two different slugs must land on two different
		Teams — the migration never collapses or cross-wires ownership."""
		slug_a, slug_b = f"{self.slug}-a", f"{self.slug}-b"
		subs = {}
		for slug in (slug_a, slug_b):
			sub = frappe.get_doc(
				{"doctype": "Subscription", "team": make_billing_team(make_user()).name}
			).insert(ignore_permissions=True)
			frappe.db.sql(
				"UPDATE `tabSubscription` SET team = %s WHERE name = %s", (slug, sub.name)
			)
			subs[slug] = sub.name

		_run_migration()

		team_a = frappe.db.get_value("Subscription", subs[slug_a], "team")
		team_b = frappe.db.get_value("Subscription", subs[slug_b], "team")
		# Each row points at the Team minted for ITS slug — and the two differ.
		self.assertEqual(frappe.db.get_value("Team", team_a, "team_name"), slug_a)
		self.assertEqual(frappe.db.get_value("Team", team_b, "team_name"), slug_b)
		self.assertNotEqual(team_a, team_b)
