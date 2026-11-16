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
	// Problems stand out: a failed event is red, a late, slow or repeated one amber.
	// A time is a problem over the column's slow_seconds, which the report sets.
	problemColors: {
		failed: "red",
		delivered_late: "orange",
		slow: "orange",
		repeat_deliveries: "orange",
		delivery_p95_seconds: "orange",
		delivery_worst_seconds: "orange",
		p95_seconds: "orange",
		worst_seconds: "orange",
	},
	formatter(value, row, column, data, default_formatter) {
		const text = default_formatter(value, row, column, data);
		const color = this.problemColors[column.fieldname];
		const isProblem = data && color && value > (column.slow_seconds ?? 0);
		return isProblem
			? `<span class="indicator-pill ${color}">${text}</span>`
			: text;
	},
};
