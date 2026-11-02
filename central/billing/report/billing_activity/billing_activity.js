// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Activity"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
		},
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date" },
		{ fieldname: "team", label: __("Team"), fieldtype: "Link", options: "Team" },
		{
			fieldname: "category",
			label: __("Flow"),
			fieldtype: "Select",
			options: [
				"",
				"Billing Profile",
				"Subscription",
				"Customer Sync",
				"Invoice",
				"Payment",
				"Payment Method",
				"Credit",
				"Webhook",
				"Billing Run",
				"Other",
			],
		},
		{ fieldname: "outcome", label: __("Outcome"), fieldtype: "Select", options: ["", "Failed", "Success"] },
	],
};
