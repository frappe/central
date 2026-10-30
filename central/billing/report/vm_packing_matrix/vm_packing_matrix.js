// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["VM Packing Matrix"] = {
	filters: [
		{
			"fieldname": "region",
			"label": __("Region"),
			"fieldtype": "Link",
			"options": "Region"
		}
	],
};
