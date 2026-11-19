// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Run Coverage"] = {
	filters: [
		{
			fieldname: "period_end",
			label: __("Month"),
			fieldtype: "Link",
			options: "Billing Run",
			description: __("Empty shows the month that just closed."),
		},
		{
			fieldname: "stage",
			label: __("Result"),
			fieldtype: "Select",
			options: [
				"",
				"Invoiced",
				"Waiting",
				"Needs Action",
				"Waived (Internal)",
				"Below Minimum",
				"Nothing to Bill",
				"No Subscription",
			],
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const text = default_formatter(value, row, column, data);
		if (column.fieldname !== "stage" || !data) return text;
		const colors = { "Needs Action": "red", Waiting: "orange", Invoiced: "green" };
		const color = colors[data.stage] || "gray";
		return `<span class="indicator-pill ${color}">${text}</span>`;
	},
};
