frappe.listview_settings['Blocked Domain'] = {
	add_fields: ['enabled'],
	get_indicator(document) {
		return document.enabled
			? [__('Enabled'), 'green', 'enabled,=,1']
			: [__('Disabled'), 'gray', 'enabled,=,0']
	},
}
