// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("WireGuard Device", {
	refresh(frm) {
		if (frm.doc.status !== "Removing") return;

		if (frm.doc.last_error) frm.set_intro(frappe.utils.escape_html(frm.doc.last_error), "red");
		frm.add_custom_button(__("Retry Removal"), async () => {
			const { message: removed } = await frm.call({ doc: frm.doc, method: "retry_removal", freeze: true });
			if (removed) frappe.set_route("List", "WireGuard Device");
			else frm.reload_doc();
		});
	},
});
