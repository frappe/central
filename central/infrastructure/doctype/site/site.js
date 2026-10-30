frappe.ui.form.on('Site', {
	refresh(form) {
		if (form.is_new()) return
		if (form.doc.rename_error)
			form.set_intro(frappe.utils.escape_html(form.doc.rename_error), 'red')
		show_trial_intro(form)
		if (!frappe.user.has_role('System Manager')) return

		add_trial_actions(form)

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

function show_trial_intro(form) {
	const { trial_state, trial_ends_on, trial_deletes_on, trial_error } = form.doc
	if (trial_error) return form.set_intro(frappe.utils.escape_html(trial_error), 'red')
	if (trial_state === 'Active')
		form.set_intro(__('Free trial. It ends on {0}, and then the server stops. Server access is locked until the trial converts.', [frappe.datetime.str_to_user(trial_ends_on)]), 'blue')
	if (trial_state === 'Ended')
		form.set_intro(__('Trial ended. The server is stopped and is deleted on {0}. Server access is locked until the trial converts.', [frappe.datetime.str_to_user(trial_deletes_on)]), 'orange')
}

function add_trial_actions(form) {
	const state = form.doc.trial_state
	if (['Active', 'Ended'].includes(state))
		form.add_custom_button(
			__('Extend Trial'),
			() =>
				frappe.prompt(
					{ fieldname: 'days', fieldtype: 'Int', label: __('Days to add'), reqd: 1, default: 7 },
					({ days }) => form.call('extend_trial', { days }).then(() => form.reload_doc()),
					__('Extend Trial'),
					__('Extend'),
				),
			__('Trial'),
		)
	if (state === 'Active')
		form.add_custom_button(
			__('End Trial Now'),
			() =>
				frappe.confirm(__('End this trial now? The server stops today.'), () =>
					form.call('end_trial_now').then(() => form.reload_doc()),
				),
			__('Trial'),
		)
	if (form.doc.trial_error)
		form.add_custom_button(
			__('Retry Trial Step'),
			() => form.call('retry_trial_step').then(() => form.reload_doc()),
			__('Trial'),
		)
}
