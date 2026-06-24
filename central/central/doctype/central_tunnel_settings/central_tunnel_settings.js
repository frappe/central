// Central Tunnel Settings — Single. Central is the WireGuard hub for every Atlas
// cluster (central/spec/TUNNEL.md). Initialize Hub brings up wg0 on the Central host
// (idempotent) and records the hub's public key; the result surfaces as a toast.

frappe.ui.form.on("Central Tunnel Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Initialize Hub"), () => {
			frappe.show_alert({ message: __("Bringing up the hub…"), indicator: "blue" });
			frm.call("initialize_hub").then(({ message }) => {
				const error = message && message.error;
				frappe.show_alert({
					message: error
						? __("Failed: {0}", [error])
						: __("Hub active. Public key: {0}", [message.public_key]),
					indicator: error ? "red" : "green",
				});
				frm.reload_doc(); // pick up hub_public_key / hub_status written server-side
			});
		});
	},
});
