frappe.listview_settings['Site'] = {
	add_fields: ['trial_state'],
	get_indicator(doc) {
		const colors = { Active: 'blue', Ended: 'orange', Converted: 'green', Deleted: 'gray' }
		if (doc.trial_state)
			return [__(doc.trial_state), colors[doc.trial_state], `trial_state,=,${doc.trial_state}`]
	},
}
