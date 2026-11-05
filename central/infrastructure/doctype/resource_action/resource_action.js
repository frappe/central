frappe.ui.form.on("Resource Action", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.error_message) frm.set_intro(frappe.utils.escape_html(frm.doc.error_message), "red");
		if (frm.doc.resource_type === "Site" && frm.doc.action === "create") render_setup_timeline(frm);
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

async function render_setup_timeline(frm) {
	const { message: steps } = await frm.call({ method: "get_setup_timeline", doc: frm.doc, type: "GET" });
	const rows = steps.map((step) => {
		const when = step.at ? frappe.datetime.str_to_user(step.at) : "";
		const indicator = step.error ? "red" : step.at ? "green" : "gray";
		const detail = step.error ? frappe.utils.escape_html(step.error) : when;
		return `<tr><td><span class="indicator-pill ${indicator}">${frappe.utils.escape_html(step.label)}</span></td><td class="text-muted">${detail}</td></tr>`;
	});
	frm.fields_dict.setup_timeline.$wrapper.html(`<table class="table table-sm">${rows.join("")}</table>`);
}
