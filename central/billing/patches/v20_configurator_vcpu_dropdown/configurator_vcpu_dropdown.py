# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan Configurator's start_vcpu / ceiling_vcpu move from Float to a Select of
clean t-shirt sizes (1/16 … 1024). The doctype sync can't cast a fraction default
like '1/8' against the existing decimal column (it does float('1/8')), so widen
the columns to varchar here — before sync — and rewrite stored numbers to their
matching dropdown label so the Select shows them.
"""

import frappe

from central.billing.catalog.configurator import VCPU_CHOICES, parse_vcpu

COLUMNS = ("start_vcpu", "ceiling_vcpu")


def execute():
	if not frappe.db.table_exists("Plan Configurator"):
		return

	for column in COLUMNS:
		if frappe.db.has_column("Plan Configurator", column):
			# Fixed table/column literals — no user input in this DDL.
			frappe.db.sql_ddl(f"ALTER TABLE `tabPlan Configurator` MODIFY `{column}` varchar(140)")

	# Existing decimal values became strings ('0.125'); map each back to its label.
	label_for = {round(parse_vcpu(choice), 6): choice for choice in VCPU_CHOICES}
	for row in frappe.get_all("Plan Configurator", fields=["name", *COLUMNS]):
		for column in COLUMNS:
			label = label_for.get(round(parse_vcpu(row.get(column)), 6))
			if label and row.get(column) != label:
				frappe.db.set_value("Plan Configurator", row.name, column, label, update_modified=False)
