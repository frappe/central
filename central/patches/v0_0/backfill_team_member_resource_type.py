# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill Team Member.resource_type for rows that predate the field.

Team Member now supports multiple role grants per user, each optionally scoped
to a resource_type ("All Servers", "All Sites", "Server", "Site"). The field's
default only applies to new rows; existing rows in the DB are left NULL until
touched, so this backfills them to "All Servers" (their prior, implicit scope).
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabTeam Member`
		SET `resource_type` = 'All Servers'
		WHERE `resource_type` IS NULL OR `resource_type` = ''
		"""
	)
