from unittest.mock import call, patch

from frappe.tests import UnitTestCase

from central.patches.v0_0.rename_region_fields import execute


class TestRegionFieldMigration(UnitTestCase):
	@patch("central.patches.v0_0.rename_region_fields.drop_index_if_exists")
	@patch("central.patches.v0_0.rename_region_fields.frappe.db.sql_ddl")
	@patch("central.patches.v0_0.rename_region_fields.rename_field")
	@patch("central.patches.v0_0.rename_region_fields.frappe.db.has_column", return_value=True)
	def test_moves_both_populated_legacy_fields(self, has_column, rename, sql_ddl, drop_index):
		execute()

		has_column.assert_has_calls(
			[
				call("Virtual Machine", "cluster"),
				call("Virtual Machine", "region"),
				call("Resource Action", "atlas_instance"),
				call("Resource Action", "region"),
			]
		)
		rename.assert_has_calls(
			[
				call("Virtual Machine", "cluster", "region"),
				call("Resource Action", "atlas_instance", "region"),
			]
		)
		drop_index.assert_has_calls(
			[
				call("tabVirtual Machine", "unique_cluster_atlas_vm_id"),
				call("tabVirtual Machine", "cluster_index"),
				call("tabResource Action", "atlas_instance_remote_vm_id_index"),
				call("tabResource Action", "atlas_instance_index"),
			]
		)
		sql_ddl.assert_has_calls(
			[
				call("ALTER TABLE `tabVirtual Machine` DROP COLUMN `cluster`"),
				call("ALTER TABLE `tabResource Action` DROP COLUMN `atlas_instance`"),
			]
		)

	@patch("central.patches.v0_0.rename_region_fields.drop_index_if_exists")
	@patch("central.patches.v0_0.rename_region_fields.frappe.db.sql_ddl")
	@patch("central.patches.v0_0.rename_region_fields.rename_field")
	@patch(
		"central.patches.v0_0.rename_region_fields.frappe.db.has_column",
		side_effect=[False, True, True],
	)
	def test_continues_after_partial_application(self, _has_column, rename, sql_ddl, drop_index):
		execute()

		rename.assert_called_once_with("Resource Action", "atlas_instance", "region")
		self.assertEqual(drop_index.call_count, 2)
		sql_ddl.assert_called_once_with("ALTER TABLE `tabResource Action` DROP COLUMN `atlas_instance`")

	@patch("central.patches.v0_0.rename_region_fields.drop_index_if_exists")
	@patch("central.patches.v0_0.rename_region_fields.frappe.db.sql_ddl")
	@patch("central.patches.v0_0.rename_region_fields.rename_field")
	@patch("central.patches.v0_0.rename_region_fields.frappe.db.has_column", return_value=False)
	def test_repeat_execution_does_nothing(self, _has_column, rename, sql_ddl, drop_index):
		execute()

		rename.assert_not_called()
		drop_index.assert_not_called()
		sql_ddl.assert_not_called()

	@patch("central.patches.v0_0.rename_region_fields.frappe.db.has_column", side_effect=[True, False])
	def test_stops_when_schema_sync_did_not_add_the_new_field(self, _has_column):
		with self.assertRaisesRegex(RuntimeError, "Virtual Machine.region must exist"):
			execute()
