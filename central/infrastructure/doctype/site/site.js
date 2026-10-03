frappe.ui.form.on('Site', {
	refresh(form) {
		if (
			!frappe.user.has_role('System Manager') ||
			!form.doc.rename_error ||
			form.doc.rename_task
		)
			return

		form.add_custom_button(__('Retry Site Rename'), () => {
			form.call('retry_subdomain_rename').then(() => form.reload_doc())
		})
	},
})
