// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pilot Credential", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Active" || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Revoke"), () =>
			frappe.confirm(__("Revoke this credential? Its Pilot can no longer reach Central."), async () => {
				await frm.call({ doc: frm.doc, method: "revoke_from_desk", freeze: true });
				await frm.reload_doc();
			}),
		);
	},
});
