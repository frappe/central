# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Point each credit wallet at the ledger entry that set its balance, so the drift guard can check it."""
	last_entry = {}
	for entry in frappe.get_all(
		"Credit Ledger Entry",
		fields=["name", "team", "currency"],
		order_by="creation asc, name asc",
	):
		last_entry[(entry.team, entry.currency)] = entry.name

	for wallet in frappe.get_all("Credit Wallet", fields=["name", "team", "currency", "last_entry"]):
		entry = last_entry.get((wallet.team, wallet.currency))
		if entry and wallet.last_entry != entry:
			frappe.db.set_value("Credit Wallet", wallet.name, "last_entry", entry, update_modified=False)
