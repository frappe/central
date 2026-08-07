// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Collection Outlook"] = {
	filters: [
		{ fieldname: "as_of", label: __("As of"), fieldtype: "Date",
		  default: frappe.datetime.get_today() },
		{ fieldname: "horizon_days", label: __("Acting within (days)"), fieldtype: "Select",
		  options: ["", "7", "14", "21", "30"], default: "21" },
		{ fieldname: "currency", label: __("Currency"), fieldtype: "Link", options: "Currency" },
		{ fieldname: "team", label: __("Team"), fieldtype: "Link", options: "Team" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "suspends_on" && data && data.suspends_on) {
			value = `<span class="indicator-pill red">${value}</span>`;
		}
		// A clock we pushed is our doing, not theirs — say so where it is read.
		if (column.fieldname === "clock_starts_on" && data && data.clock_deferred) {
			value = `${value} <span class="text-muted">${__("(deferred)")}</span>`;
		}
		return value;
	},
};
