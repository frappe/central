// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Invoice Register"] = {
	filters: [
		{
			fieldname: "from_date",
			reqd: 1,
			label: __("From (Period Start)"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			reqd: 1,
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
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Draft", "Open", "Paid", "Overdue", "Waived", "Cancelled"].join("\n"),
		},
		{
			fieldname: "invoice_type",
			label: __("Invoice Type"),
			fieldtype: "Select",
			options: ["", "Billable", "Cost Report"].join("\n"),
			default: "Billable",
		},
		{
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
	],
};
