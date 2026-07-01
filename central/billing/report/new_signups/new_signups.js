// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["New Signups"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Signed Up From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -3),
		},
		{
			fieldname: "to_date",
			label: __("Signed Up To"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
		},
	],
};
