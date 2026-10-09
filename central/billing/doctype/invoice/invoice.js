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
			frm.add_custom_button(__("Refund Part"), () => refund_part(frm));
			frm.add_custom_button(__("Cancel and Refund"), () =>
				ask_reason(
					frm,
					__("Cancel and Refund"),
					"cancel_and_refund",
					__("Cancelled. Refunds and the credit note are under way.")
				)
			);
		}
		if (frm.doc.__onload?.failed_refunds) {
			frm.add_custom_button(__("Retry Failed Refunds"), () =>
				frappe
					.call({
						method: `${CORRECTIONS_API}.retry_failed_refunds`,
						args: { invoice: frm.doc.name },
						freeze: true,
					})
					.then(({ message }) => {
						frappe.show_alert({
							message: __("Trying {0} refund(s) again", [message.retried]),
							indicator: "blue",
						});
						frm.reload_doc();
					})
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

function refund_part(frm) {
	const left = frm.doc.__onload?.refundable || 0;
	const card = frm.doc.__onload?.card_refundable || 0;
	const currency = frm.doc.currency;
	frappe.prompt(
		[
			{
				fieldname: "amount",
				fieldtype: "Currency",
				options: "currency",
				label: __("Amount, GST included"),
				reqd: 1,
				description: __("Less than {0}, what is left of this invoice.", [format_currency(left, currency)]),
			},
			{
				fieldname: "destination",
				fieldtype: "Select",
				label: __("Refund to"),
				options: [
					{ value: "Wallet", label: __("Wallet") },
					{ value: "Source", label: __("Card or UPI that paid") },
				],
				default: "Wallet",
				reqd: 1,
				description: card
					? __("The card or UPI can take back up to {0}.", [format_currency(card, currency)])
					: __("No card or UPI paid this invoice, so it goes to the wallet."),
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		(values) =>
			frappe
				.call({
					method: `${CORRECTIONS_API}.refund_part`,
					args: { invoice: frm.doc.name, ...values },
					freeze: true,
				})
				.then(() => {
					frappe.show_alert({ message: __("Refund under way, with its credit note"), indicator: "green" });
					frm.reload_doc();
				}),
		__("Refund Part of the Invoice"),
		__("Refund")
	);
}
