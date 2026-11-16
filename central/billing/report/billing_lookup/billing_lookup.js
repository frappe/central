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
			options: [
				"Billing Events",
				"Subscriptions",
				"Subscription Changes",
				"Payment Methods",
				"Open Invoices",
			],
			default: "Billing Events",
		},
	],
	pillColors: {
		Failed: "red",
		Expired: "red",
		Overdue: "red",
		Suspended: "red",
		Paused: "orange",
		"Past Due": "orange",
		"Pending Validation": "orange",
		Upgrade: "orange",
		Downgrade: "blue",
		Outstanding: "blue",
		"Billing stopped": "gray",
		"Billing started": "green",
		Running: "green",
		Current: "green",
		Active: "green",
		Success: "green",
	},
	pillColumns: ["status", "outcome", "effect", "state", "account_standing"],
	formatter(value, row, column, data, default_formatter) {
		// An event that moved no money has no amount; Frappe would draw it as 0.00.
		if (
			["amount", "monthly_cost", "cost_after", "cost_change"].includes(column.fieldname) &&
			value == null
		) {
			return "";
		}
		if (data && data.is_total) {
			const shown =
				column.fieldname === "plan"
					? frappe.utils.escape_html(value || "")
					: default_formatter(value, row, column, data);
			return `<b>${shown}</b>`;
		}
		const text = default_formatter(value, row, column, data);
		if (!data || !value) {
			return text;
		}
		if (this.pillColumns.includes(column.fieldname)) {
			return `<span class="indicator-pill ${this.pillColors[value] || "gray"}">${text}</span>`;
		}
		if (column.fieldname === "hold_reason") {
			return `<span class="indicator-pill orange">${text}</span>`;
		}
		if (column.fieldname === "failure_reason") {
			return `<span class="${data.status === "Active" ? "text-warning" : "text-danger"}">${text}</span>`;
		}
		if (column.fieldname === "money_meaning" && data.money_unexplained) {
			return `<span class="text-danger">${text}</span>`;
		}
		if (column.fieldname === "cost_change" && value > 0) {
			return `+${text}`;
		}
		return text;
	},
};
