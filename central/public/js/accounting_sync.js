// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Preview and Send Now for the forms whose records go to the accounting system:
// Billing Profile, Credit Ledger Entry and Invoice. The server decides what is sent.
frappe.provide("central.billing");

central.billing.ACCOUNTING_API = "central.billing.api.admin.accounting";

central.billing.add_accounting_sync_actions = function (frm) {
	// The server offers it to operators only, and only while the sync is not Off.
	if (frm.is_new() || !frm.doc.__onload?.accounting_sync_actions) return;
	const group = __("Accounting");
	frm.add_custom_button(__("Preview"), () => preview_accounting_sync(frm), group);
	frm.add_custom_button(__("Send Now"), () => confirm_accounting_sync(frm), group);
	if (frm.doc.pdf_url || frm.doc.receipt_url) {
		frm.add_custom_button(__("Fetch PDF Again"), () => fetch_pdf_again(frm), group);
	}
	if (frm.doctype === "Billing Profile" && !frm.doc.profile_id) {
		frm.add_custom_button(__("Use Existing Customer"), () => use_existing_customer(frm), group);
	}
};

// After a print format change, the kept PDF is dropped and the next download renders it again.
function fetch_pdf_again(frm) {
	frappe
		.call({
			method: `${central.billing.ACCOUNTING_API}.fetch_pdf_again`,
			args: { doctype: frm.doctype, name: frm.docname },
			freeze: true,
		})
		.then(() => {
			frappe.show_alert({ message: __("The next download renders the PDF again"), indicator: "green" });
			frm.reload_doc();
		});
}

// When a team matches more than one customer, the operator names the one to use.
function use_existing_customer(frm) {
	frappe.prompt(
		[
			{
				fieldname: "customer",
				fieldtype: "Data",
				label: __("Customer in the accounting system"),
				description: __("Its ID, as the accounting system shows it. Its currency must be the team's."),
				reqd: 1,
			},
		],
		({ customer }) =>
			frappe
				.call({
					method: `${central.billing.ACCOUNTING_API}.use_existing_customer`,
					args: { team: frm.docname, customer: customer.trim() },
					freeze: true,
				})
				.then(() => {
					frappe.show_alert({ message: __("The team now uses {0}", [customer]), indicator: "green" });
					frm.reload_doc();
				}),
		__("Use Existing Customer"),
		__("Use")
	);
}

function preview_accounting_sync(frm) {
	frappe
		.call({
			method: `${central.billing.ACCOUNTING_API}.preview_accounting_sync`,
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

function confirm_accounting_sync(frm) {
	frappe.confirm(
		__(
			"Send {0} to the accounting system now? The team's customer and its advances are sent first when they are missing. Central does not delete what it makes there.",
			[frm.docname]
		),
		() =>
			frappe
				.call({
					method: `${central.billing.ACCOUNTING_API}.send_to_accounting`,
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
