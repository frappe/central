import frappe


def execute():
	"""Carry the two old observation clocks into `state_observed_at`.

	`last_event_at` (event push) and `last_synced_at` (scoped read) tracked the same
	fact through two writers. Central now owns the record and keeps one clock, so each
	server takes the newer of the two values it already had.

	This runs after the model sync, where the new column exists and the two removed
	fields survive as orphan columns. Both guards below keep it safe on a fresh install
	and on a site whose orphan columns are already trimmed."""
	if not frappe.db.has_column("Asset", "state_observed_at"):
		return

	for column in ("last_event_at", "last_synced_at"):
		if not frappe.db.has_column("Asset", column):
			continue

		asset = frappe.qb.DocType("Asset")
		(
			frappe.qb.update(asset)
			.set(asset.state_observed_at, asset[column])
			.where(asset[column].isnotnull())
			.where(asset.state_observed_at.isnull() | (asset.state_observed_at < asset[column]))
		).run()
