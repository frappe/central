// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Metal Server", {
	refresh(frm) {
		frm.sidebar.clear_user_actions();
		if (frm.doc.bmc_url) frm.add_web_link(frm.doc.bmc_url, __("Open BMC"));

		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Link Atlas Host"), async () => {
			await frm.call({ doc: frm.doc, method: "link_atlas_host" });
			frm.reload_doc();
		});

		for (const [kind, label] of [["root", __("Root")], ["bmc", __("BMC")]]) {
			frm.add_custom_button(__("Show {0} Credentials", [label]), () =>
				show_credentials(frm, kind, __("{0} Credentials", [label])),
			);
		}
	},
});

async function show_credentials(frm, kind, title) {
	const { message } = await frm.call({ doc: frm.doc, method: "get_credentials", args: { kind } });
	const dialog = new frappe.ui.Dialog({
		title,
		fields: [
			{ fieldname: "username", fieldtype: "Password", label: __("Username") },
			{ fieldname: "password", fieldtype: "Password", label: __("Password") },
		],
	});
	dialog.show();
	dialog.set_values(message);
	dialog.$wrapper.find("input").prop("readonly", true);
}
