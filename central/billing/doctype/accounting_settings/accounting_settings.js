// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

const API = "central.billing.api.admin.accounting";

frappe.ui.form.on("Accounting Settings", {
	refresh(frm) {
		if (!frm.doc.__onload?.sync_enabled) {
			frm.set_intro(__("The accounting sync is off, so these settings are not in use."), "orange");
			frm.disable_form();
			return;
		}
		frm.add_custom_button(__("Check Setup"), () => run(frm, "check_accounting_setup", "GET"));
		frm.add_custom_button(__("Create Missing"), () => {
			frappe.confirm(
				__("Create the missing records in the accounting system? Existing records are not changed."),
				() => run(frm, "create_missing_accounting_setup", "POST")
			);
		});
	},
});

function run(frm, method, type) {
	frappe.call({ method: `${API}.${method}`, type, freeze: true }).then(({ message }) => {
		show_report(message || []);
		frm.reload_doc();
	});
}

function show_report(rows) {
	const colour = {
		Exists: "green",
		Created: "green",
		Updated: "blue",
		Incomplete: "orange",
		Missing: "red",
		Failed: "red",
	};
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
