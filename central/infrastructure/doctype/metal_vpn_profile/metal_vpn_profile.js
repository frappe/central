// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Metal VPN Profile", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Download Profile"), () =>
			open_url_post("/api/method/run_doc_method", {
				dt: frm.doc.doctype,
				dn: frm.doc.name,
				method: "download_profile",
			}),
		);
	},
});
