frappe.ui.form.on("Region", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Test Connection"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the region before testing its connection."));
				return;
			}

			const response = await frm.call({ method: "test_connection", freeze: true });
			const result = response.message;
			frappe.show_alert(
				{
					message: result.reachable ? __("Reachable") : __("Unreachable: {0}", [result.error]),
					indicator: result.reachable ? "green" : "red",
				},
				5,
			);
			await frm.reload_doc();
		});
	},
});
