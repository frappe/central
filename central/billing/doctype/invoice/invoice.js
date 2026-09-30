// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

const CORRECTIONS_API = "central.billing.api.admin.corrections";

frappe.ui.form.on("Invoice", {
	refresh(frm) {
		if (["Draft", "Open", "Overdue"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Cancel"), () =>
				ask_reason(frm, __("Cancel Invoice"), "cancel_invoice", __("Invoice cancelled"))
			);
		}
		if (frm.doc.status === "Paid" && frm.doc.invoice_type === "Billable") {
			frm.add_custom_button(__("Cancel and Refund"), () =>
				ask_reason(
					frm,
					__("Cancel and Refund"),
					"cancel_and_refund",
					__("Cancelled. Refunds and the credit note are under way.")
				)
			);
		}
	},
});

function ask_reason(frm, title, method, done_message) {
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
		({ reason }) =>
			frappe
				.call({
					method: `${CORRECTIONS_API}.${method}`,
					args: { invoice: frm.doc.name, reason },
					freeze: true,
				})
				.then(() => {
					frappe.show_alert({ message: done_message, indicator: "green" });
					frm.reload_doc();
				}),
		title,
		__("Confirm")
	);
}
