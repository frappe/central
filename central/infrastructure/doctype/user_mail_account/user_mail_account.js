// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("User Mail Account", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Assigned") return;

		frm.add_custom_button(__("Remove Mailbox"), () =>
			frappe.confirm(__("Remove this mailbox from the Suite site? Its server can no longer send mail."), () =>
				frm.call({ doc: frm.doc, method: "revoke", freeze: true }).then(() => frm.reload_doc()),
			),
		);
	},
});
