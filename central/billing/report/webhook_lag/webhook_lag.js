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
	formatter(value, row, column, data, default_formatter) {
		const text = default_formatter(value, row, column, data);
		if (!data || !(value > 0)) return text;
		const color = webhookLagColor(column.fieldname, value);
		return color
			? `<span class="indicator-pill ${color}">${text}</span>`
			: text;
	},
};

// Seconds over a minute, as the report counts a late or slow event.
const SLOW_SECONDS = 60;
const COUNT_COLORS = {
	failed: "red",
	delivered_late: "orange",
	slow: "orange",
	repeat_deliveries: "orange",
};

function webhookLagColor(fieldname, value) {
	if (COUNT_COLORS[fieldname]) return COUNT_COLORS[fieldname];
	const isSecondsOverLimit =
		fieldname.endsWith("_seconds") &&
		!fieldname.includes("median") &&
		value > SLOW_SECONDS;
	return isSecondsOverLimit ? "orange" : null;
}
