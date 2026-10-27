// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("WireGuard Device", {
	refresh(frm) {
		if (frm.is_new() || !frm.perm[0]?.delete) return;

		const remove = async () => {
			const { message: removed } = await frm.call({ doc: frm.doc, method: "remove_device", freeze: true });
			if (removed) frappe.set_route("List", "WireGuard Device");
			else frm.reload_doc();
		};

		if (frm.doc.status === "Removing") {
			if (frm.doc.last_error) frm.set_intro(frappe.utils.escape_html(frm.doc.last_error), "red");
			frm.add_custom_button(__("Retry Removal"), remove);
			return;
		}

		frm.add_custom_button(__("Remove Device"), () =>
			frappe.confirm(__("Remove {0}? It stops reaching the team's servers.", [frm.doc.title.bold()]), remove)
		);
	},
});
