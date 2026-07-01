// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Payment Method Mix"] = {
	filters: [
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
		{
			fieldname: "gateway",
			label: __("Gateway"),
			fieldtype: "Link",
			options: "Payment Gateway",
		},
	],
};
