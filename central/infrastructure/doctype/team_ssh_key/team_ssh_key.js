// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Team SSH Key", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.last_sync_error) return;

		frm.set_intro(frappe.utils.escape_html(frm.doc.last_sync_error), "red");
		frm.add_custom_button(__("Retry Sync"), async () => {
			await frm.call({ doc: frm.doc, method: "retry_sync", freeze: true });
			frappe.show_alert({ message: __("Sync queued"), indicator: "blue" }, 5);
		});
	},
});
