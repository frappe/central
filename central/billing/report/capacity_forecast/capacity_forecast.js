// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Capacity Forecast"] = {
	filters: [
		{
			"fieldname": "region",
			"label": __("Region"),
			"fieldtype": "Link",
			"options": "Region"
		},
		{
			"fieldname": "lead_days",
			"label": __("Days to Buy and Install"),
			"fieldtype": "Int",
			"default": 45
		}
	],
};
