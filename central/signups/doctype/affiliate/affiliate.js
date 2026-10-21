frappe.ui.form.on('Affiliate', {
	refresh(form) {
		if (form.is_new() || !frappe.user.has_role('System Manager')) return

		add_review_actions(form)
	},
})

function add_review_actions(form) {
	const run = (method, args) => form.call(method, args).then(() => form.reload_doc())
	const status = form.doc.status

	if (status === 'Pending') {
		form.add_custom_button(__('Approve'), () =>
			frappe.confirm(__('Approve {0} as an affiliate?', [form.doc.user]), () => run('approve')),
		)
		form.add_custom_button(__('Reject'), () =>
			frappe.prompt(
				{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason'), reqd: 1 },
				({ reason }) => run('reject', { reason }),
				__('Reject Request'),
				__('Reject'),
			),
		)
	}
	if (status === 'Active')
		form.add_custom_button(__('Disable'), () =>
			frappe.confirm(__('Disable this affiliate? Their account shows as paused until you enable it.'), () => run('disable')),
		)
	if (status === 'Disabled')
		form.add_custom_button(__('Enable'), () =>
			frappe.confirm(__('Enable this affiliate again with the same code?'), () => run('enable')),
		)
}
