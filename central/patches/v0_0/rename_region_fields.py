import frappe
from frappe.database.utils import drop_index_if_exists
from frappe.model.utils.rename_field import rename_field

REGION_FIELDS = (
	(
		"Virtual Machine",
		"cluster",
		"region",
		("unique_cluster_atlas_vm_id", "cluster_index"),
	),
	(
		"Resource Action",
		"atlas_instance",
		"region",
		("atlas_instance_remote_vm_id_index", "atlas_instance_index"),
	),
)


def execute() -> None:
	"""Move legacy region values into the canonical fields once schema sync adds them."""
	for doctype, old_field, new_field, legacy_indexes in REGION_FIELDS:
		if not frappe.db.has_column(doctype, old_field):
			continue
		if not frappe.db.has_column(doctype, new_field):
			raise RuntimeError(f"{doctype}.{new_field} must exist before migrating {old_field}")

		rename_field(doctype, old_field, new_field)
		for index in legacy_indexes:
			drop_index_if_exists(f"tab{doctype}", index)
		frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{old_field}`")
