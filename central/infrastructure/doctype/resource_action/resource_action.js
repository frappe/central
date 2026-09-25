frappe.ui.form.on("Resource Action", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Queued", "Dispatching", "Sent", "In Progress", "Uncertain"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Check Progress"), async () => {
				await frm.call("check_status");
				await frm.reload_doc();
			});
		}
		// A creation that never reached a VM is the only thing safe to send again.
		if (frm.doc.action === "create" && ["Failed", "Timed Out"].includes(frm.doc.status) && !frm.doc.remote_vm_id) {
			frm.add_custom_button(__("Retry Creation"), async () => {
				await frm.call({ doc: frm.doc, method: "retry", freeze: true });
				await frm.reload_doc();
			});
		}
	},
});
