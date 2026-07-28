// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Backend", {
	refresh(frm) {
		if (frm.is_new()) return;

		const label = frm.doc.is_active ? __("Rotate Credential") : __("Enroll");
		frm.add_custom_button(label, () => enroll(frm));
	},
});

function enroll(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the backend before enrolling."));
		return;
	}

	frappe.prompt(
		{
			fieldname: "bootstrap_secret",
			label: __("Bootstrap Secret"),
			fieldtype: "Password",
			reqd: 1,
		},
		({ bootstrap_secret }) => {
			frm.call("enroll", { bootstrap_secret }).then(() => {
				frappe.show_alert({ message: __("Enrolled and activated."), indicator: "green" });
				frm.reload_doc();
			});
		},
		__("Enroll {0}", [frm.doc.service]),
		__("Enroll")
	);
}
