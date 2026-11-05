// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Bare Metal Capacity"] = {
	filters: [
		{
			"fieldname": "region",
			"label": __("Region"),
			"fieldtype": "Link",
			"options": "Region"
		},
		{
			"fieldname": "metal_server",
			"label": __("Metal Server"),
			"fieldtype": "Link",
			"options": "Metal Server"
		}
	],
};
