frappe.ui.form.on('Blocked Domain', {
	refresh(form) {
		if (form.is_new() || !form.doc.enabled || !frappe.user.has_role('System Manager')) return

		form.add_custom_button(__('Find conflicting assignments'), () => {
			form.call({ method: 'find_conflicts', freeze: true }).then(({ message: conflicts }) => {
				const rows = conflicts.map((row) => [
					frappe.utils.get_form_link(row.doctype, row.name, true),
					frappe.utils.escape_html(row.domain),
					frappe.utils.get_form_link('Team', row.team, true),
				])
				frappe.msgprint({
					title: __('Conflicting assignments'),
					message: rows.length
						? [[__('Record'), __('Domain'), __('Team')], ...rows]
						: __('No existing assignments match this reservation.'),
					as_table: rows.length > 0,
					wide: true,
				})
			})
		})
		form.set_intro(__('Use Find conflicting assignments to review existing domains. This reservation does not remove routes.'), 'blue')
	},
})
