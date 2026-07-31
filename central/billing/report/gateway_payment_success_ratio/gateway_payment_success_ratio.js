// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Gateway Payment Success Ratio"] = {
	filters: [
		{
			fieldname: "from_date",
			reqd: 1,
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -1),
		},
		{
			fieldname: "to_date",
			reqd: 1,
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "gateway",
			label: __("Gateway"),
			fieldtype: "Link",
			options: "Payment Gateway",
		},
		{
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Gateway", "Month", "Failure Code"].join("\n"),
			default: "Gateway",
		},
	],
};
