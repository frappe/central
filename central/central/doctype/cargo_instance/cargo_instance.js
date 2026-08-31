// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cargo Instance", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Test Connection"), () =>
			frm.call("test_connection").then(({ message }) => {
				frappe.msgprint({
					title: message.reachable ? __("Reachable") : __("Unreachable"),
					indicator: message.reachable ? "green" : "red",
					message: message.reachable
						? __("Configured: {0}, clusters: {1}", [message.configured, message.clusters])
						: message.error,
				});
				frm.reload_doc();
			})
		);

		if (frm.doc.status !== "Disabled") {
			const again = frm.doc.status === "Registered";
			frm.add_custom_button(again ? __("Re-register") : __("Register"), () =>
				frappe.confirm(
					again
						? __("Mint a new token and overwrite this host's settings? Its current token stops working.")
						: __("Push settings to {0}?", [frm.doc.base_url]),
					() =>
						frm.call("register").then(() => {
							frappe.show_alert({ message: __("Registered."), indicator: "green" });
							frm.reload_doc();
						})
				)
			).addClass(again ? "" : "btn-primary");
		}
	},
});
