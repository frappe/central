// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Lookup"] = {
	filters: [
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
			reqd: 1,
		},
		{
			fieldname: "view",
			label: __("Show"),
			fieldtype: "Select",
			options: ["Billing Events", "Payment Methods", "Open Invoices"],
			default: "Billing Events",
		},
	],
	statusColors: {
		Failed: "red",
		Expired: "red",
		Overdue: "red",
		Paused: "orange",
		"Pending Validation": "orange",
		Outstanding: "blue",
		Active: "green",
		Success: "green",
	},
	formatter(value, row, column, data, default_formatter) {
		// An event that moved no money has no amount; Frappe would draw it as 0.00.
		if (column.fieldname === "amount" && !value) {
			return "";
		}
		const text = default_formatter(value, row, column, data);
		if (!data || !value) {
			return text;
		}
		if (["status", "outcome"].includes(column.fieldname)) {
			return `<span class="indicator-pill ${this.statusColors[value] || "gray"}">${text}</span>`;
		}
		if (column.fieldname === "hold_reason") {
			return `<span class="indicator-pill orange">${text}</span>`;
		}
		if (column.fieldname === "failure_reason") {
			return `<span class="${data.status === "Active" ? "text-warning" : "text-danger"}">${text}</span>`;
		}
		return text;
	},
};
