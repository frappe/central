frappe.ui.form.on("Partner Link", {
	refresh(frm) {
		const is_operator = frappe.user.has_role("System Manager");
		if (!frm.is_new() && frm.doc.status === "Active" && is_operator) {
			frm.add_custom_button(__("End Link"), () => end_link(frm), __("Actions"));
		}
	},
});

function end_link(frm) {
	frappe.prompt(
		[
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"The partner loses access to this team now. The partner managers of both teams get the reason. If the partner pays for this team, it pays to the end of this month.",
				)}</p>`,
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		(values) =>
			frappe
				.call("central.api.partners.end_partner_link", {
					link: frm.doc.name,
					reason: values.reason,
				})
				.then(() => frm.reload_doc()),
		__("End Partner Link"),
		__("End Link"),
	);
}
