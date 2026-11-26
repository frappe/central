// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Usage Month", {
	refresh: (frm) => add_mark_credited(frm),
});

// Shown while a lower value for a billed day waits for its credit note. The operator
// issues the credit note first, then records it here.
function add_mark_credited(frm) {
	const due = (frm.doc.corrections || []).filter((row) => row.status === "Credit Due");
	if (!due.length || !frappe.user.has_role("System Manager")) return;
	frm.add_custom_button(__("Mark Credited"), () =>
		frappe.prompt(
			[
				{
					fieldname: "correction",
					label: __("Correction"),
					fieldtype: "Select",
					reqd: 1,
					options: due.map((row) => ({
						value: row.name,
						label: __("Day {0}: billed {1}, now {2}", [row.day, row.billed_value, row.value]),
					})),
				},
				{
					fieldname: "reason",
					label: __("Credit note or refund"),
					fieldtype: "Data",
					reqd: 1,
				},
			],
			(values) =>
				frappe
					.call({
						method: "central.billing.api.admin.corrections.mark_usage_credited",
						args: values,
						freeze: true,
					})
					.then(() => frm.reload_doc()),
			__("Mark Credited")
		)
	);
}
