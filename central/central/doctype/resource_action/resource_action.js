frappe.ui.form.on("Resource Action", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Queued", "Dispatching", "Sent", "In Progress", "Uncertain"].includes(frm.doc.status)) {
			if (frm.doc.remote_vm_id) {
				frm.add_custom_button(__("Check Progress"), async () => {
					await frm.call("check_status");
					await frm.reload_doc();
				});
			}
		}
		if (frm.doc.status !== "Uncertain" || frm.doc.remote_vm_id || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Locate Created VM"), () => {
			frappe.prompt({ fieldname: "remote_vm_id", fieldtype: "Data", label: __("Atlas VM ID"), reqd: 1 }, async (values) => {
				await frm.call({ method: "resolve_created_vm", args: values, freeze: true });
				await frm.reload_doc();
			}, __("Verify the VM belongs to this creation action"));
		});
	},
});
