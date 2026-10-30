// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Bare Metal Yield"] = {
	filters: [
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Region", "Metal Server"],
			default: "Region",
			reqd: 1,
		},
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
