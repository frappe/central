// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Allocation vs Usage"] = {
	filters: [
		{
			"fieldname": "region",
			"label": __("Region"),
			"fieldtype": "Link",
			"options": "Region"
		},
		{
			"fieldname": "team",
			"label": __("Team"),
			"fieldtype": "Link",
			"options": "Team"
		},
		{
			"fieldname": "days",
			"label": __("Days"),
			"fieldtype": "Int",
			"default": 7
		}
	],
};
