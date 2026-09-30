frappe.ui.form.on('Central SSO Settings', {
	refresh(frm) {
		if (frappe.user.has_role('System Manager') && !frm.doc.atlas_key_id) {
			frm.add_custom_button(__('Initialize Atlas Signing Key'), async () => {
				await frm.call('initialize_atlas_signing_key')
				await frm.reload_doc()
			})
		}
	},
})
