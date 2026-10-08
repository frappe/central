frappe.ui.form.on("Team Invitation", {
	refresh(frm) {
		if (frm.doc.status !== "Pending") {
			return;
		}

		frm.add_custom_button(__("Resend"), () =>
			frappe
				.call("central.api.teams.resend_invitation", { invitation: frm.doc.name })
				.then(() => frm.reload_doc())
		);
		frm.add_custom_button(__("Revoke"), () =>
			frappe.confirm(__("Revoke this invitation?"), () =>
				frappe
					.call("central.api.teams.revoke_invitation", { invitation: frm.doc.name })
					.then(() => frm.reload_doc())
			)
		);
	},
});
