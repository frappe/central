// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Involuntary Churn"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -6),
		},
		{
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
		},
	],
};
