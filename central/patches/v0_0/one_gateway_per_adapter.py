# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collapse Payment Gateway to one row per adapter, named after the adapter.

Gateway rows used to be user-named, so a site could hold several rows for the same
provider — but nothing could route between them. The webhook spine resolves a
gateway from the callback URL, and there is one URL per adapter; the currency
resolvers picked "the first enabled row with this adapter". Duplicates therefore
resolved arbitrarily. The row is now named after its adapter, which makes the
duplicate impossible at the database level.

This patch picks a survivor per adapter, folds the losers' currency rows into it,
repoints every Link that referenced a loser, then renames the survivor to its
adapter_key. The `title` column is left in place for the DocType sync to drop.
"""

import frappe

# Every doctype with a Link to Payment Gateway. Renaming the survivor is handled by
# frappe.rename_doc, but the losers are deleted, so their references must be moved
# by hand first.
GATEWAY_LINKS = (
	"Gateway Customer",
	"Payment Method",
	"Payment Attempt",
	"Webhook Event",
	"Subscription",
)


def execute():
	for adapter_key, names in _rows_by_adapter().items():
		survivor = _pick_survivor(names)
		for loser in names:
			if loser == survivor:
				continue
			_fold_currencies(loser, survivor)
			_repoint_links(loser, survivor)
			frappe.delete_doc("Payment Gateway", loser, force=True, ignore_permissions=True)
		if survivor != adapter_key:
			if frappe.db.exists("Payment Gateway", adapter_key):
				# A row already sits on the target name but carries a different
				# adapter_key — data we must not silently destroy.
				frappe.log_error(
					title="Payment Gateway rename blocked",
					message=f"Cannot rename {survivor} to {adapter_key}: that name is taken.",
				)
				continue
			frappe.rename_doc("Payment Gateway", survivor, adapter_key, force=True, show_alert=False)


def _rows_by_adapter() -> dict[str, list[str]]:
	rows = frappe.get_all("Payment Gateway", fields=["name", "adapter_key"], order_by="creation asc")
	by_adapter: dict[str, list[str]] = {}
	for row in rows:
		if not row.adapter_key:
			continue
		by_adapter.setdefault(row.adapter_key, []).append(row.name)
	return by_adapter


def _pick_survivor(names: list[str]) -> str:
	"""The row whose credentials the site is actually running on.

	Prefer enabled, then validated, then oldest — the losers' keys are discarded, so
	this must land on the row that is live today.
	"""
	rows = frappe.get_all(
		"Payment Gateway",
		filters={"name": ["in", names]},
		fields=["name", "is_enabled", "credentials_validated_at", "creation"],
	)
	rows.sort(key=lambda r: (not r.is_enabled, not r.credentials_validated_at, r.creation))
	return rows[0].name


def _fold_currencies(loser: str, survivor: str):
	"""Move the loser's currency rows onto the survivor, skipping currencies it
	already handles. An is_default row wins only if the survivor has no default for
	that currency — the survivor's own config is authoritative."""
	survivor_rows = {
		row.currency: row
		for row in frappe.get_all(
			"Payment Gateway Currency",
			filters={"parent": survivor},
			fields=["name", "currency", "is_default"],
		)
	}
	for row in frappe.get_all(
		"Payment Gateway Currency",
		filters={"parent": loser},
		fields=["name", "currency", "is_default"],
	):
		existing = survivor_rows.get(row.currency)
		if existing:
			if row.is_default and not existing.is_default:
				frappe.db.set_value(
					"Payment Gateway Currency", existing.name, "is_default", 1, update_modified=False
				)
			continue
		frappe.db.set_value(
			"Payment Gateway Currency",
			row.name,
			{"parent": survivor, "is_default": row.is_default},
			update_modified=False,
		)
		survivor_rows[row.currency] = frappe._dict(
			name=row.name, currency=row.currency, is_default=row.is_default
		)


def _repoint_links(loser: str, survivor: str):
	for doctype in GATEWAY_LINKS:
		if not frappe.db.table_exists(doctype):
			continue
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table.gateway, survivor).where(table.gateway == loser).run()
