// Desk buttons for the Central → Atlas command path (central/api/servers.py). The
// server methods re-check capability (server:power / server:terminate) and that
// the asset belongs to the team, so these buttons just call them by id.
frappe.ui.form.on("Asset", {
	refresh(frm) {
		if (frm.is_new()) return;

		const run = (label, method, indicator) =>
			frappe
				.call({
					method: `central.api.servers.${method}`,
					args: { team: frm.doc.team, resource_id: frm.doc.resource_id },
					freeze: true,
					freeze_message: __("{0}…", [label]),
				})
				.then((r) => {
					if (r.exc) return;
					frappe.show_alert(
						{ message: __("{0} requested (task {1})", [label, r.message.task]), indicator },
						5,
					);
				});

		frm.add_custom_button(__("Start"), () => run(__("Start"), "start_server", "green"), __("Server"));
		frm.add_custom_button(__("Stop"), () => run(__("Stop"), "stop_server", "orange"), __("Server"));
		frm.add_custom_button(
			__("Terminate"),
			() =>
				frappe.confirm(__("Terminate {0}?", [frm.doc.resource_id]), () =>
					run(__("Terminate"), "terminate_server", "red"),
				),
			__("Server"),
		);
	},
});
