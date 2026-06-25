// "Test Connection" pings the Atlas API and records reachability; "Register" runs the
// full Central-driven tunnel registration handshake (server methods
// AtlasInstance.test_connection / AtlasInstance.register).
frappe.ui.form.on("Atlas Instance", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Test Connection"), () =>
			frm.call("test_connection").then((r) => {
				const result = r.message || {};
				frappe.show_alert(
					{
						message: result.reachable
							? __("Reachable")
							: __("Unreachable: {0}", [result.error || ""]),
						indicator: result.reachable ? "green" : "red",
					},
					5,
				);
				frm.reload_doc();
			}),
		);

		// While the tunnel is up (Active) offer Remove Tunnel; otherwise offer Register,
		// which brings the tunnel up — for an Unregistered instance it also creates the
		// identity, for an Inactive (already-registered) one it just re-tunnels.
		if (frm.doc.tunnel_status === "Active") {
			frm.add_custom_button(__("Remove Tunnel"), () =>
				frappe.confirm(
					__(
						"Strip the tunnel + firewall for {0}? This reverts the Atlas's management firewall (restoring public access) and tears down wg0, but keeps it registered (Inactive) — Register brings the tunnel back.",
						[frm.doc.region],
					),
					() =>
						frm
							.call("remove_tunnel")
							.then((r) => {
								const result = r.message || {};
								frappe.show_alert(
									{
										message: __("Tunnel removed ({0})", [
											result.tunnel_status || "Inactive",
										]),
										indicator: "orange",
									},
									5,
								);
								frm.reload_doc();
							})
							.catch(() => frm.reload_doc()),
				),
			);
		} else {
			const label = frm.doc.tunnel_status === "Inactive" ? __("Register (re-tunnel)") : __("Register");
			frm.add_custom_button(label, () =>
				frappe.confirm(
					__(
						"Register {0}? This brings up the tunnel and locks the Atlas's public interface behind it.",
						[frm.doc.region],
					),
					() =>
						frm
							.call("register")
							.then((r) => {
								const result = r.message || {};
								frappe.show_alert(
									{
										message: __("Registered: tunnel {0} ({1})", [
											result.tunnel_ip || "",
											result.tunnel_status || "",
										]),
										indicator: "green",
									},
									5,
								);
								frm.reload_doc();
							})
							.catch(() => frm.reload_doc()),
				),
			);
		}
	},
});
