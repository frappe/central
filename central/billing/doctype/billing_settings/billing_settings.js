// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

const ACCOUNTING_API = "central.billing.api.admin.accounting";

frappe.ui.form.on("Billing Settings", {
	refresh(frm) {
		// The accounting setup is usable only while the accounting sync is on.
		if (!frm.doc.__onload?.accounting_sync_enabled) return;

		frm.add_custom_button(__("Check Accounting Setup"), () => check_setup(frm));
	},
});

frappe.ui.form.on("Accounting Gateway Account", {
	gateway(frm, cdt, cdn) {
		// The mode of payment is usually named after the gateway. Never overwrite one already set.
		const row = locals[cdt][cdn];
		if (row.gateway && !row.mode_of_payment) {
			frappe.model.set_value(cdt, cdn, "mode_of_payment", row.gateway);
		}
	},
});

function check_setup(frm) {
	frappe.call({ method: `${ACCOUNTING_API}.check_accounting_setup`, type: "GET", freeze: true }).then(
		({ message }) => show_setup_report(message || [])
	);
}

function show_setup_report(rows) {
	const colour = { OK: "green", Wrong: "orange", "No Access": "orange", Missing: "red", Failed: "red" };
	const body = rows
		.map(
			(r) => `<tr>
				<td>${frappe.utils.escape_html(r.record)}</td>
				<td>${frappe.utils.escape_html(r.name || "")}</td>
				<td><span class="indicator-pill ${colour[r.state] || "gray"}">${r.state}</span></td>
				<td>${frappe.utils.escape_html(r.detail || "")}</td>
			</tr>`
		)
		.join("");
	frappe.msgprint({
		title: __("Accounting Setup"),
		wide: true,
		message: `<table class="table table-bordered"><thead><tr>
			<th>${__("Record")}</th><th>${__("Name")}</th><th>${__("State")}</th><th>${__("Detail")}</th>
			</tr></thead><tbody>${body}</tbody></table>`,
	});
}
