// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

const ACCOUNTING_API = "central.billing.api.admin.accounting";

frappe.ui.form.on("Billing Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Test Alert"), () => send_test_alert(frm));

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

function send_test_alert(frm) {
	// The alert goes through the saved settings, so unsaved changes would not be tested.
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the settings before you send a test alert."));
		return;
	}
	frm.call({ method: "send_test_alert", doc: frm.doc, freeze: true }).then(({ message }) => {
		const sent_to = message || [];
		frappe.msgprint({
			title: __("Test Alert"),
			indicator: sent_to.length ? "green" : "red",
			message: sent_to.length
				? __("Sent to {0}.", [sent_to.join(", ")])
				: __("Not sent. See the Error Log for the reason."),
		});
	});
}

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
