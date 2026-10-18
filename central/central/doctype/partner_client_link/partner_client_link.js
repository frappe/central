frappe.ui.form.on("Partner Client Link", {
	refresh(frm) {
		if (!["Requested", "Active"].includes(frm.doc.status) || !frm.perm[0]?.write) {
			return;
		}

		frm.add_custom_button(__("End Link"), () =>
			frappe.prompt(
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason"),
					description: __("The partner stops working with this customer. This can't be undone."),
				},
				({ reason }) =>
					frm.call("end_link", { reason }).then(() => frm.reload_doc()),
				__("End this link?"),
				__("End Link")
			)
		);
	},
});
