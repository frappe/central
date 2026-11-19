// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Invariant Violations"] = {
	filters: [
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: ["Detail", "Summary"],
			default: "Summary",
		},
		{
			fieldname: "kind",
			label: __("Kind"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("All") },
				{ value: "Money", label: __("Money invariants") },
				{ value: "Readiness", label: __("Billing readiness") },
			],
		},
		{
			fieldname: "check",
			label: __("Check"),
			fieldtype: "Data",
			description: __("A check code from the Summary view, such as C2 or T1."),
		},
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
	],
};
