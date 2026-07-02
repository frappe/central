// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Refunds Report"] = {
	filters: [
		{
			fieldname: "from_date",
			reqd: 1,
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -1),
		},
		{
			fieldname: "to_date",
			reqd: 1,
			label: __("To"),
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
			options: ["", "Initiated", "Completed", "Failed"].join("\n"),
		},
		{
			fieldname: "destination",
			label: __("Destination"),
			fieldtype: "Select",
			options: ["", "Source", "Wallet"].join("\n"),
		},
	],
};
