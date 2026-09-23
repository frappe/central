// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

// Desk actions call the same methods the console does. The server re-checks the
// capability and team, so a button is only a trigger.
frappe.ui.form.on("VM Snapshot", {
	refresh(frm) {
		if (frm.is_new()) return;

		const call = (method, args, message) =>
			frappe
				.call({ method: `central.api.snapshots.${method}`, args: { team: frm.doc.team, ...args }, freeze: true })
				.then((r) => {
					if (r.exc) return;
					frappe.show_alert({ message, indicator: "green" }, 5);
					frm.reload_doc();
				});

		if (frm.doc.status === "Pending") {
			frm.add_custom_button(__("Sync"), () =>
				frm.call({ method: "sync", freeze: true, freeze_message: __("Asking the region…") }).then(() =>
					frm.reload_doc(),
				),
			);
		}
		if (frm.doc.status === "Available" && frm.doc.expires_at) {
			frm.add_custom_button(__("Keep"), () =>
				frappe.confirm(__("Keep this snapshot? It is no longer deleted on its own. It costs money once two newer snapshots of its server exist."), () =>
					call("keep_snapshot", { name: frm.doc.name }, __("Snapshot kept")),
				),
			);
		}
		if (["Available", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Delete from region"), () =>
				frappe.confirm(__("Delete this snapshot from its region? This can't be undone."), () =>
					call("delete_snapshots", { names: [frm.doc.name] }, __("Snapshot deleted")),
				),
			);
		}
	},
});
