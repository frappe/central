from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.identity.doctype.team.tenant import (
	MAXIMUM_TENANT_ID,
	allocate_tenant_id,
	prepare_tenant_id_series,
	validate_tenant_id,
)
from central.patches.v0_0 import backfill_team_tenant_ids


class TestTeamTenantId(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def make_team(self, **values):
		return frappe.get_doc(
			{"doctype": "Team", "team_name": "Tenant test", "owner_user": "Administrator", **values}
		).insert()

	def test_caller_cannot_select_another_teams_tenant(self):
		first = self.make_team()
		second = self.make_team(tenant_id=first.tenant_id)
		self.assertGreater(first.tenant_id, 0)
		self.assertGreater(second.tenant_id, first.tenant_id)
		self.assertLessEqual(second.tenant_id, MAXIMUM_TENANT_ID)

	def test_operator_cannot_change_existing_tenant(self):
		team = self.make_team()
		team.tenant_id += 1
		with self.assertRaises(frappe.CannotChangeConstantError):
			team.save()

	def test_rename_keeps_tenant_identity(self):
		team = self.make_team()
		tenant_id = team.tenant_id
		team.team_name = "Renamed tenant test"
		team.save()
		self.assertEqual(team.tenant_id, tenant_id)

	def test_customer_cannot_change_own_or_another_teams_tenant(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "tenant-owner@example.test",
				"first_name": "Tenant Owner",
				"send_welcome_email": 0,
				"roles": [{"role": "Central User"}],
			}
		).insert()
		own = self.make_team(owner_user=user.name)
		other = self.make_team()
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")
		own.tenant_id += 1
		with self.assertRaises(frappe.CannotChangeConstantError):
			own.save()
		other.tenant_id += 1
		with self.assertRaises(frappe.PermissionError):
			other.save()

	def test_database_refuses_duplicate_tenant(self):
		first = self.make_team()
		second = self.make_team()
		second.tenant_id = first.tenant_id
		with self.assertRaises(frappe.UniqueValidationError):
			second.db_update()

	def test_invalid_identifiers_are_rejected(self):
		for value in (None, 0, -1, True, 1.5, "7", MAXIMUM_TENANT_ID + 1):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				validate_tenant_id(value)
		validate_tenant_id(MAXIMUM_TENANT_ID)

	def test_storage_preserves_full_unsigned_range(self):
		team = self.make_team()
		frappe.db.set_value("Team", team.name, "tenant_id", MAXIMUM_TENANT_ID)
		self.assertEqual(frappe.db.get_value("Team", team.name, "tenant_id"), MAXIMUM_TENANT_ID)

	def test_allocator_refuses_exhausted_range(self):
		with (
			patch("central.identity.doctype.team.tenant.getseries", return_value=str(MAXIMUM_TENANT_ID + 1)),
			self.assertRaises(frappe.ValidationError),
		):
			allocate_tenant_id()

	def test_setup_does_not_reuse_a_deleted_teams_identifier(self):
		team = self.make_team()
		tenant_id = team.tenant_id
		frappe.delete_doc("Team", team.name)
		prepare_tenant_id_series()
		self.assertGreater(self.make_team().tenant_id, tenant_id)

	def test_setup_advances_past_preserved_mapping(self):
		team = self.make_team()
		existing = team.tenant_id + 100
		frappe.db.set_value("Team", team.name, "tenant_id", existing)
		prepare_tenant_id_series()
		self.assertGreater(allocate_tenant_id(), existing)

	def test_concurrent_allocations_are_distinct(self):
		with ThreadPoolExecutor(max_workers=4) as workers:
			values = list(workers.map(self.allocate_in_connection, [frappe.local.site] * 8))
		self.assertEqual(len(set(values)), len(values))

	@staticmethod
	def allocate_in_connection(site: str) -> int:
		frappe.init(site)
		frappe.connect()
		try:
			value = allocate_tenant_id()
			# Commit only the reserved sequence value, as independent signup transactions do.
			frappe.db.commit()
			return value
		finally:
			frappe.destroy()

	def test_patch_preserves_mappings_and_is_repeatable(self):
		preserved = self.make_team()
		missing = self.make_team()
		frappe.db.set_value("Team", missing.name, "tenant_id", 0)
		rows = [
			frappe._dict(name=preserved.name, tenant_id=preserved.tenant_id),
			frappe._dict(name=missing.name, tenant_id=0),
		]
		with (
			patch.object(backfill_team_tenant_ids.frappe, "get_all", return_value=rows),
			patch.object(backfill_team_tenant_ids, "validate_unassigned_teams"),
		):
			backfill_team_tenant_ids.execute()
			rows[1].tenant_id = frappe.db.get_value("Team", missing.name, "tenant_id")
			backfill_team_tenant_ids.execute()
		self.assertEqual(frappe.db.get_value("Team", preserved.name, "tenant_id"), preserved.tenant_id)
		self.assertGreater(rows[1].tenant_id, preserved.tenant_id)
		self.assertEqual(frappe.db.get_value("Team", missing.name, "tenant_id"), rows[1].tenant_id)

	def test_patch_refuses_duplicate_preserved_mappings(self):
		rows = [frappe._dict(name=name, tenant_id=7) for name in ("first", "second")]
		with self.assertRaises(frappe.ValidationError):
			backfill_team_tenant_ids.validate_existing_mappings(rows)

	def test_patch_refuses_to_guess_existing_resource_ownership(self):
		resource = frappe._dict(name="remote-vm", team="existing-team")
		with (
			patch.object(backfill_team_tenant_ids.frappe, "get_all", return_value=[resource]),
			self.assertRaises(frappe.ValidationError),
		):
			backfill_team_tenant_ids.validate_unassigned_teams([resource.team])
