// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cargo Instance", {
	refresh(frm) {
		if (frm.is_new()) return;

		const label = frm.doc.status === "Registered" ? __("Re-issue Bootstrapping Token") : __("Issue Bootstrapping Token");
		frm.add_custom_button(label, () =>
			frappe.confirm(
				frm.doc.status === "Registered"
					? __("This host is already registered. Issuing a new token lets it enrol again and replaces its current tokens. Continue?")
					: __("Issue a short-lived token for this host?"),
				() =>
					frm.call("issue_bootstrapping_token").then(({ message }) => {
						frappe.msgprint({
							title: __("Pass this to the host's setup.sh"),
							indicator: "orange",
							message: `<pre>CENTRAL_BOOTSTRAPPING_TOKEN=${frappe.utils.escape_html(message.bootstrapping_token)}</pre>
								<p>${__("It is shown once and expires shortly.")}</p>`,
						});
						frm.reload_doc();
					})
			)
		).addClass(frm.doc.status === "Registered" ? "" : "btn-primary");
	},
});
