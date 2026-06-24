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
	},
});
