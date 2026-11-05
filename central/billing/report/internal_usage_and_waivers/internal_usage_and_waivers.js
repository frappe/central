// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Internal Usage and Waivers"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Period From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -3),
		},
		{
			fieldname: "to_date",
			label: __("Period To"),
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
