// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Usage Month", {
	refresh: (frm) => {
		add_mark_credited(frm);
		add_mark_billed_by_hand(frm);
	},
});

// Shown while a lower value for a billed day waits for its credit note. The operator
// issues the credit note first, then records it here.
function add_mark_credited(frm) {
	const due = (frm.doc.corrections || []).filter((row) => row.status === "Credit Due");
	add_settle_button(frm, {
		rows: due,
		title: __("Mark Credited"),
		row_label: (row) => __("Day {0}: billed {1}, now {2}", [row.day, row.billed_value, row.value]),
		reason_label: __("Credit note or refund"),
		method: "central.billing.api.admin.corrections.mark_usage_credited",
	});
}

// Shown while a reissue left the units a correction added for billing by hand (readiness M7).
// The operator bills them first, then records it here.
function add_mark_billed_by_hand(frm) {
	const left = (frm.doc.corrections || []).filter(
		(row) => row.status === "Written Off" && row.invoice
	);
	add_settle_button(frm, {
		rows: left,
		title: __("Mark Billed By Hand"),
		row_label: (row) =>
			__("Day {0}: {1} on reissued {2}, bill {3}", [
				row.day,
				row.value,
				row.invoice,
				row.billable_delta,
			]),
		reason_label: __("Invoice that billed it"),
		method: "central.billing.api.admin.corrections.mark_usage_billed_by_hand",
	});
}

function add_settle_button(frm, { rows, title, row_label, reason_label, method }) {
	if (!rows.length || !frappe.user.has_role("System Manager")) return;
	frm.add_custom_button(title, () =>
		frappe.prompt(
			[
				{
					fieldname: "correction",
					label: __("Correction"),
					fieldtype: "Select",
					reqd: 1,
					options: rows.map((row) => ({ value: row.name, label: row_label(row) })),
				},
				{ fieldname: "reason", label: reason_label, fieldtype: "Data", reqd: 1 },
			],
			(values) => frappe.call({ method, args: values, freeze: true }).then(() => frm.reload_doc()),
			title
		)
	);
}
