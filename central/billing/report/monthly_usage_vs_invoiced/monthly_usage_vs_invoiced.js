// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Monthly Usage vs Invoiced"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From (Period Start)"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -2),
		},
		{
			fieldname: "to_date",
			label: __("To (Period Start)"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
	],
};
