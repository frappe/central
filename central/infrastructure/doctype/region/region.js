frappe.ui.form.on("Region", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Test Connection"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the region before testing its connection."));
				return;
			}

			const response = await frm.call({ doc: frm.doc, method: "test_connection", freeze: true });
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

		update_enroll_buttons(frm);
	},

	on_tab_change(frm) {
		update_enroll_buttons(frm);
	},
});

function update_enroll_buttons(frm) {
	// Each region service gets its enrollment button only on its own tab, so the two
	// never compete for space or get clicked for the wrong region service.
	frm.remove_custom_button(__("Enroll Atlas"));
	frm.remove_custom_button(__("Enroll Cargo"));

	const active_tab = frm.get_active_tab()?.df?.fieldname;

	if (active_tab === "atlas_tab") {
		frm.add_custom_button(__("Enroll Atlas"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the region before enrolling its Atlas."));
				return;
			}

			await frm.call({ doc: frm.doc, method: "enroll_atlas", freeze: true });
			frappe.show_alert({ message: __("Atlas enrolled"), indicator: "green" }, 5);
			await frm.reload_doc();
		});
	}

	if (active_tab === "cargo_tab" && frm.doc.cargo_status === "Draft") {
		frm.add_custom_button(__("Enroll Cargo"), async () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the region before enrolling its Cargo."));
				return;
			}

			await frm.call({ doc: frm.doc, method: "enroll_cargo", freeze: true });
			frappe.show_alert({ message: __("Cargo enrolled"), indicator: "green" }, 5);
			await frm.reload_doc();
		});
	}
}
