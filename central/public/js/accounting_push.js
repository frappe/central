// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Preview and Send Now for the forms whose records go to the accounting system:
// Billing Profile, Credit Ledger Entry and Invoice. The server decides what is sent.
frappe.provide("central.billing");

central.billing.ACCOUNTING_API = "central.billing.api.admin.accounting";

central.billing.add_accounting_push = function (frm) {
	// The server offers it to operators only, and only while the sync is not Off.
	if (frm.is_new() || !frm.doc.__onload?.accounting_push) return;
	const group = __("Accounting");
	frm.add_custom_button(__("Preview"), () => preview_accounting_push(frm), group);
	frm.add_custom_button(__("Send Now"), () => confirm_accounting_push(frm), group);
};

function preview_accounting_push(frm) {
	frappe
		.call({
			method: `${central.billing.ACCOUNTING_API}.preview_accounting_push`,
			type: "GET",
			args: { doctype: frm.doctype, name: frm.docname },
			freeze: true,
		})
		.then(({ message }) => {
			const sections = Object.entries(message || {})
				.map(
					([title, payload]) => `<h5>${frappe.utils.escape_html(title)}</h5>
					<pre>${frappe.utils.escape_html(JSON.stringify(payload, null, 2))}</pre>`
				)
				.join("");
			frappe.msgprint({ title: __("What Send Now would post"), wide: true, message: sections });
		});
}

function confirm_accounting_push(frm) {
	frappe.confirm(
		__(
			"Send {0} to the accounting system now? The team's customer and its advances are sent first when they are missing. Central does not delete what it makes there.",
			[frm.docname]
		),
		() =>
			frappe
				.call({
					method: `${central.billing.ACCOUNTING_API}.push_to_accounting`,
					args: { doctype: frm.doctype, name: frm.docname },
					freeze: true,
					freeze_message: __("Sending to the accounting system"),
				})
				.then(({ message }) => {
					frappe.msgprint({
						title: __("Sent"),
						message: `<pre>${frappe.utils.escape_html(JSON.stringify(message, null, 2))}</pre>`,
					});
					frm.reload_doc();
				})
	);
}
