// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Metal Server Profitability"] = {
	filters: [
		{
			fieldname: "region",
			label: __("Region"),
			fieldtype: "Link",
			options: "Region",
		},
		{
			fieldname: "usd_to_inr",
			label: __("USD to INR Rate"),
			fieldtype: "Float",
		},
	],
};
