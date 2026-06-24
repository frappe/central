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

		// Register locks the Atlas behind the tunnel — confirm before driving it.
		// Once tunnelled, offer Remove Tunnel (the inverse) instead.
		if (frm.doc.tunnel_status === "Unregistered" || !frm.doc.tunnel_status) {
			frm.add_custom_button(__("Register"), () =>
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
		} else {
			frm.add_custom_button(__("Remove Tunnel"), () =>
				frappe.confirm(
					__(
						"Remove the tunnel + firewall for {0}? This reverts the Atlas's management firewall (restoring public access), tears down wg0, removes the hub peer, and deletes its service user.",
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
											result.tunnel_status || "Unregistered",
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
		}
	},
});
