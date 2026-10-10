// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("User Mail Account", {
	refresh(frm) {
		if (frm.is_new() || !["Available", "Assigned"].includes(frm.doc.status)) return;

		const message =
			frm.doc.status === "Assigned"
				? __("Remove this mailbox from the Suite site? Its server can no longer send mail.")
				: __("Remove this mailbox from the Suite site?");
		frm.add_custom_button(__("Remove Mailbox"), () =>
			frappe.confirm(message, () =>
				frm.call({ doc: frm.doc, method: "revoke", freeze: true }).then(() => frm.reload_doc()),
			),
		);
	},
});
