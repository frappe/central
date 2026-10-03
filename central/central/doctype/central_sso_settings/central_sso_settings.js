const SIGNING_KEYS = [
	{ plane: 'atlas', key_id: 'atlas_key_id', label: __('Initialize Atlas Signing Key') },
	{ plane: 'pilot', key_id: 'pilot_key_id', label: __('Initialize Pilot Signing Key') },
	{ plane: 'oidc', key_id: 'oidc_key_id', label: __('Initialize OIDC Signing Key') },
]

frappe.ui.form.on('Central SSO Settings', {
	refresh(frm) {
		if (!frappe.user.has_role('System Manager')) return

		for (const key of SIGNING_KEYS) {
			if (frm.doc[key.key_id]) continue
			frm.add_custom_button(key.label, async () => {
				await frm.call('initialize_signing_key', { plane: key.plane })
				await frm.reload_doc()
			})
		}
	},
})
