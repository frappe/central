// "Test Connection" pings the Atlas API and records reachability (server method
// AtlasInstance.test_connection).
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
	},
});
