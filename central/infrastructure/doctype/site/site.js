frappe.ui.form.on('Site', {
	refresh(form) {
		if (form.is_new()) return
		if (form.doc.rename_error)
			form.set_intro(frappe.utils.escape_html(form.doc.rename_error), 'red')
		if (!frappe.user.has_role('System Manager')) return

		form.add_custom_button(
			__('Check Readiness'),
			async () => {
				const response = await form.call('check_readiness')
				frappe.show_alert(
					{
						message: response.message ? __('The site answers') : __('The site does not answer'),
						indicator: response.message ? 'green' : 'orange',
					},
					5,
				)
				form.reload_doc()
			},
			__('Site'),
		)
		form.add_custom_button(
			__('Open as Administrator'),
			() =>
				frappe.confirm(
					__('Open this site as Administrator? The login is recorded on the site and its server.'),
					async () => {
						const response = await form.call({ method: 'open_as_administrator', freeze: true })
						if (response.message) window.open(response.message, '_blank')
					},
				),
			__('Site'),
		)

		if (form.doc.rename_error && !form.doc.rename_task)
			form.add_custom_button(__('Retry Site Rename'), () => {
				form.call('retry_subdomain_rename').then(() => form.reload_doc())
			})
	},
})
