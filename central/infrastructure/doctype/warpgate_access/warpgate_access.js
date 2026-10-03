// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('Warpgate Access', {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === 'Active' && frm.doc.access_type !== 'Admin') {
			frm.add_custom_button(__('Show SSH Command'), () => show_ssh_command(frm))
		}
		load_hosts(frm)
	},

	region(frm) {
		frm.hosts = null
		frm.set_value({ host: null, host_title: null })
		load_hosts(frm)
	},

	access_type(frm) {
		load_hosts(frm)
	},

	host_title(frm) {
		const host = (frm.hosts || []).find((item) => item.title === frm.doc.host_title)
		frm.set_value('host', host ? host.id : null)
	},
})

async function load_hosts(frm) {
	const field = frm.fields_dict.host_title
	if (frm.doc.docstatus !== 0 || frm.doc.access_type !== 'One host' || !frm.doc.region) {
		field.set_data([])
		return
	}
	if (!frm.hosts) {
		const { message } = await frappe.call({
			method: 'central.infrastructure.doctype.warpgate_access.warpgate_access.get_hosts',
			args: { region: frm.doc.region },
			type: 'GET',
		})
		frm.hosts = message || []
	}
	field.set_data(frm.hosts.map((host) => ({ label: host.title, value: host.title, description: host.status })))
}

async function show_ssh_command(frm) {
	const { message } = await frm.call({ method: 'get_ssh_command', doc: frm.doc, type: 'GET' })
	const dialog = new frappe.ui.Dialog({
		title: __('SSH Command'),
		fields: [
			{ fieldname: 'command', fieldtype: 'Code', read_only: 1, default: message },
			{
				fieldtype: 'HTML',
				options: `<p class="text-muted small">${__(
					'Open the link that Warpgate prints, sign in with Central, and approve the login.'
				)}</p>`,
			},
		],
		primary_action_label: __('Copy'),
		primary_action() {
			frappe.utils.copy_to_clipboard(message)
			dialog.hide()
		},
	})
	dialog.show()
}
