frappe.ui.form.on("Team", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Invite Member"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Invite Member"),
				fields: [
					{ fieldname: "email", fieldtype: "Data", label: __("Email"), reqd: 1 },
					{
						fieldname: "role",
						fieldtype: "Link",
						label: __("Team Role"),
						options: "Team Role",
						reqd: 1,
					},
				],
				primary_action_label: __("Invite"),
				primary_action(values) {
					frm.call("invite_member", values).then(() => {
						dialog.hide();
						frappe.show_alert({
							message: __("Invitation created"),
							indicator: "green",
						});
					});
				},
			});
			dialog.show();
		});
	},
});
