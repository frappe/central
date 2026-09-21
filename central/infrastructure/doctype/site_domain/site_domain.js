// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Site Domain", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Active" || !frm.perm[0]?.write) return;

		frm.add_custom_button(__("Retry"), () =>
			frm
				.call({ method: "retry", doc: frm.doc, freeze: true, freeze_message: __("Updating proxy…") })
				.then(() => frm.reload_doc()),
		);
	},
});
