// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.listview_settings['Warpgate Access'] = {
	get_indicator(doc) {
		const colors = { Active: 'green', Expired: 'gray', Revoked: 'red' }
		if (doc.docstatus === 0) return [__('Draft'), 'gray', 'docstatus,=,0']
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`]
	},
}
