// Desk buttons for the Central → Atlas command path (central/api/servers.py). The
// server methods re-check capability (server:power / server:terminate) and that
// the server belongs to the team, so these buttons just call them by id.
frappe.ui.form.on("Virtual Machine", {
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
						{ message: __("{0} requested: {1}", [label, r.message.status]), indicator },
						5,
					);
				});

		if (frm.doc.atlas_vm_id && frm.doc.status !== "Terminated") {
			frm.add_custom_button(
				__("Sync state"),
				async () => {
					const response = await frm.call({
						doc: frm.doc,
						method: "sync_state",
						freeze: true,
						freeze_message: __("Asking the region…"),
					});
					if (response.exc) return;
					frappe.show_alert(
						{ message: __("The region reports {0}", [response.message.status]), indicator: "blue" },
						5,
					);
					await frm.reload_doc();
				},
				__("Server"),
			);
		}

		if (frm.doc.status === "Terminated") {
			frm.add_custom_button(__("Remove routes"), () =>
				frappe.confirm(__("Remove every site and domain route of {0}?", [frm.doc.resource_id]), () =>
					frm.call({ doc: frm.doc, method: "remove_routes", freeze: true }).then((r) => {
						if (r.exc) return;
						frappe.show_alert({ message: __("Route removal queued"), indicator: "blue" }, 5);
					}),
				),
			);
			return;
		}

		frm.add_custom_button(
			__("Take snapshot"),
			() =>
				frappe
					.call({
						method: "central.api.snapshots.take_snapshot",
						args: { team: frm.doc.team, resource_id: frm.doc.resource_id },
						freeze: true,
					})
					.then((r) => {
						if (r.exc) return;
						frappe.show_alert({ message: __("Snapshot started"), indicator: "blue" }, 5);
					}),
			__("Server"),
		);
		frm.add_custom_button(__("Start"), () => run(__("Start"), "start_server", "green"), __("Server"));
		frm.add_custom_button(__("Stop"), () => run(__("Stop"), "stop_server", "orange"), __("Server"));
		if (frm.doc.status === "Running") {
			frm.add_custom_button(
				__("Restart"),
				() => run(__("Restart"), "restart_server", "orange"),
				__("Server"),
			);
		}
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
