// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Credit Wallet Movements"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
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
			fieldname: "entry_type",
			label: __("Type"),
			fieldtype: "Select",
			options: ["", "Credit", "Debit"].join("\n"),
		},
		{
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
	],
};
