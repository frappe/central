// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Free vs Paid Consumption"] = {
	filters: [
		{
			"fieldname": "group_by",
			"label": __("Group By"),
			"fieldtype": "Select",
			"options": [
				"Machine",
				"Region"
			],
			"default": "Machine",
			"reqd": 1
		},
		{
			"fieldname": "region",
			"label": __("Region"),
			"fieldtype": "Link",
			"options": "Region"
		}
	],
};
