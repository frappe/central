// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Projection"] = {
	filters: [
		{ fieldname: "batch", label: __("Batch"), fieldtype: "Link",
		  options: "Billing Projection Batch" },
		{ fieldname: "months", label: __("Months"), fieldtype: "Select",
		  options: ["1", "3", "6", "12"], default: "1" },
		{ fieldname: "currency", label: __("Currency"), fieldtype: "Link", options: "Currency" },
		{ fieldname: "country", label: __("Country"), fieldtype: "Link", options: "Country" },
		{ fieldname: "cluster", label: __("Cluster"), fieldtype: "Link", options: "Atlas Instance" },
		{ fieldname: "collection_mode", label: __("Collection mode"), fieldtype: "Select",
		  options: ["", "Stripe Auto", "E-Mandate", "Manual Checkout", "Prepaid", "Action Required"] },
		{ fieldname: "outcome", label: __("Outcome contains"), fieldtype: "Data" },
		{ fieldname: "needs_attention", label: __("Only teams that would suspend"),
		  fieldtype: "Check" },
	],

	onload(report) {
		report.page.add_inner_button(__("Project this cohort"), () => {
			const f = report.get_values();
			frappe
				.call({
					method: "central.billing.api.admin.projection.start_cohort_projection",
					args: {
						filters: JSON.stringify({
							currency: f.currency, country: f.country, cluster: f.cluster,
							collection_mode: f.collection_mode,
						}),
						months: cint(f.months) || 1,
					},
				})
				.then((r) => {
					if (!r.message) return;
					frappe.show_alert({
						message: __("Projecting {0} teams in the background.", [r.message.teams]),
						indicator: "blue",
					});
				});
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// A team that would be cut off should read as one without anybody hunting.
		if (column.fieldname === "suspends_on" && data && data.suspends_on) {
			value = `<span class="indicator-pill red">${value}</span>`;
		}
		if (column.fieldname === "outcome" && data && data.suspends_on) {
			value = `<span style="color: var(--text-on-red)">${value}</span>`;
		}
		return value;
	},
};
