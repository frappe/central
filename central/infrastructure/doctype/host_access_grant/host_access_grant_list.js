// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.listview_settings['Host Access Grant'] = {
	add_fields: ['expires_at'],
	get_indicator(doc) {
		if (doc.docstatus === 2) return [__('Revoked'), 'red', 'docstatus,=,2']
		if (doc.docstatus === 0) return [__('Draft'), 'gray', 'docstatus,=,0']
		const is_active = frappe.datetime.str_to_obj(doc.expires_at) > frappe.datetime.system_datetime(true)
		return is_active ? [__('Active'), 'green', 'docstatus,=,1'] : [__('Expired'), 'gray', 'docstatus,=,1']
	},
}
