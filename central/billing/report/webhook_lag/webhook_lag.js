// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Webhook Lag"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -14),
		},
		{
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "gateway",
			label: __("Gateway"),
			fieldtype: "Link",
			options: "Payment Gateway",
		},
	],
};
