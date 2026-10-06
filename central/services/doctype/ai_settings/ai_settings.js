// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Settings", {
	refresh(frm) {
		const label = frm.doc.control_api_key ? __("Rotate Credential") : __("Enroll");
		frm.add_custom_button(label, () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings before enrolling."));
				return;
			}
			frappe.prompt(
				{ fieldname: "bootstrap_secret", label: __("Bootstrap Secret"), fieldtype: "Password", reqd: 1 },
				({ bootstrap_secret }) =>
					frm.call("enroll", { bootstrap_secret }).then(() => {
						frappe.show_alert({ message: __("Enrolled."), indicator: "green" });
						frm.reload_doc();
					}),
				__("Enroll at Grove"),
				__("Enroll")
			);
		});
	},
});
