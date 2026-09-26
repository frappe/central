# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Zero-rating reasons are now SEZ and Overseas, matching the GST category names."""

import frappe

RENAMES = {"SEZ LUT": "SEZ", "Export": "Overseas"}


def execute():
	for doctype in ("Tax Profile", "Invoice"):
		t = frappe.qb.DocType(doctype)
		for old, new in RENAMES.items():
			frappe.qb.update(t).set(t.zero_rating_reason, new).where(t.zero_rating_reason == old).run()
