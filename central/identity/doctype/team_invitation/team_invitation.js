frappe.ui.form.on("Team Invitation", {
	refresh(frm) {
		if (frm.doc.status !== "Pending") {
			return;
		}

		if (frm.doc.email === frappe.session.user) {
			frm.add_custom_button(__("Accept"), () =>
				frm.call("accept").then(() => frm.reload_doc())
			);
		}

		if (frm.doc.email !== frappe.session.user) {
			frm.add_custom_button(__("Revoke"), () =>
				frm.call("revoke").then(() => frm.reload_doc())
			);
		}
	},
});
