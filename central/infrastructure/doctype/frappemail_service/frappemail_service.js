// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("FrappeMail Service", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.enabled) return;

		frm.add_custom_button(__("Refill Now"), () =>
			frm.call({ doc: frm.doc, method: "queue_refill", freeze: true }).then((r) => {
				if (r.exc) return;
				frappe.show_alert({ message: __("Refill queued"), indicator: "green" }, 5);
			}),
		);
	},
});
