# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.team.team import MAXIMUM_TENANT_ID


class TestTeamTenantId(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _create_team(self, team_name: str):
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": team_name,
				"owner_user": "Administrator",
			}
		).insert()

	def test_a_new_team_is_allocated_a_tenant_id(self):
		team = self._create_team("Tenant Alpha")

		self.assertGreaterEqual(team.tenant_id, 1)
		self.assertLessEqual(team.tenant_id, MAXIMUM_TENANT_ID)

	def test_two_teams_are_allocated_different_tenant_ids(self):
		first = self._create_team("Tenant Alpha")
		second = self._create_team("Tenant Beta")

		self.assertNotEqual(first.tenant_id, second.tenant_id)
		self.assertGreater(second.tenant_id, first.tenant_id)

	def test_a_supplied_tenant_id_is_discarded(self):
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Tenant Gamma",
				"owner_user": "Administrator",
				"tenant_id": 7,
			}
		).insert()

		self.assertNotEqual(team.tenant_id, 7)

	def test_tenant_id_carries_a_unique_index(self):
		self.assertIsNotNone(frappe.db.get_column_index("tabTeam", "tenant_id", unique=True))

	def test_the_unique_index_refuses_a_duplicate(self):
		first = self._create_team("Tenant Alpha")
		second = self._create_team("Tenant Beta")

		with self.assertRaises(Exception) as caught:
			frappe.db.sql(
				"UPDATE `tabTeam` SET `tenant_id` = %s WHERE `name` = %s",
				(first.tenant_id, second.name),
			)

		self.assertTrue(frappe.db.is_unique_key_violation(caught.exception))

	def test_tenant_id_cannot_be_changed(self):
		team = self._create_team("Tenant Alpha")
		team.tenant_id = team.tenant_id + 1

		self.assertRaises(frappe.CannotChangeConstantError, team.save)

	def test_a_team_without_a_usable_tenant_id_cannot_be_saved(self):
		"""Neither value is reachable through the controller; the guard catches a
		row left by a direct write or a missed backfill."""
		team = self._create_team("Tenant Alpha")

		for unusable in (None, 0):
			with self.subTest(tenant_id=unusable):
				frappe.db.set_value("Team", team.name, "tenant_id", unusable, update_modified=False)

				corrupt = frappe.get_doc("Team", team.name)

				self.assertRaises(frappe.ValidationError, corrupt.save)
