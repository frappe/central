// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Customer Profitability"] = {
	filters: [
		{
			"fieldname": "group_by",
			"label": __("Group By"),
			"fieldtype": "Select",
			"options": [
				"Team",
				"Server",
				"Service"
			],
			"default": "Team",
			"reqd": 1
		},
		{
			"fieldname": "month",
			"label": __("Month"),
			"fieldtype": "Date",
			"description": __("Any day in the month to read. Empty reads the last closed month.")
		},
		{
			"fieldname": "team",
			"label": __("Team"),
			"fieldtype": "Link",
			"options": "Team"
		}
	],
};
