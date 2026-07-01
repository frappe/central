// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Team Credit Balance"] = {
	filters: [
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
	],
};
