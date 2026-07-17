// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["MRR and YTD Revenue"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From (Period Start)"),
			fieldtype: "Date",
			default: frappe.datetime.get_today().slice(0, 4) + "-01-01",
		},
		{
			fieldname: "to_date",
			label: __("To (Period Start)"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
		{
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
	],
};
