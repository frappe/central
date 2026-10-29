// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Unit Economics"] = {
	filters: [
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Funding", "Region", "Team"],
			default: "Funding",
			reqd: 1,
		},
		{
			fieldname: "region",
			label: __("Region"),
			fieldtype: "Link",
			options: "Region",
		},
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
		{
			fieldname: "funding",
			label: __("Funding"),
			fieldtype: "Select",
			options: ["", "Paying Customer", "Not Paying Yet", "Our Own Team", "Free Trial"],
		},
		{
			fieldname: "usd_to_inr",
			label: __("USD to INR Rate"),
			fieldtype: "Float",
		},
	],
};
