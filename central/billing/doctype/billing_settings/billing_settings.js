// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

const ACCOUNTING_API = "central.billing.api.admin.accounting";

frappe.ui.form.on("Billing Settings", {
	refresh(frm) {
		// The accounting setup is usable only while the accounting sync is on.
		if (!frm.doc.__onload?.accounting_sync_enabled) return;

		const group = __("Accounting Setup");
		frm.add_custom_button(__("Check"), () => run_setup(frm, "check_accounting_setup", "GET"), group);
		frm.add_custom_button(
			__("Create Missing"),
			() =>
				frappe.confirm(
					__("Create the missing records in the accounting system? Existing records are not changed."),
					() => run_setup(frm, "create_missing_accounting_setup", "POST")
				),
			group
		);
	},
});

function run_setup(frm, method, type) {
	frappe.call({ method: `${ACCOUNTING_API}.${method}`, type, freeze: true }).then(({ message }) => {
		show_setup_report(message || []);
		frm.reload_doc();
	});
}

function show_setup_report(rows) {
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
