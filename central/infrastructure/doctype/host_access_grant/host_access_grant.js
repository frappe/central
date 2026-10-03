// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('Host Access Grant', {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && is_active(frm.doc)) {
			frm.add_custom_button(__('Show SSH Command'), () => show_ssh_command(frm))
		}
	},

	region(frm) {
		frm.hosts = null
		frm.set_value({ host: null, host_title: null })
		frm.set_df_property('host_title', 'options', [])
	},

	host_title(frm) {
		const host = (frm.hosts || []).find((item) => item.title === frm.doc.host_title)
		frm.set_value('host', host ? host.id : null)
	},

	onload_post_render(frm) {
		frm.fields_dict.host_title.$input?.on('focus', () => load_hosts(frm))
	},
})

async function load_hosts(frm) {
	if (!frm.doc.region || frm.hosts) return
	const { message } = await frappe.call({
		method: 'central.infrastructure.doctype.host_access_grant.host_access_grant.get_hosts',
		args: { region: frm.doc.region },
		type: 'GET',
	})
	frm.hosts = message || []
	frm.set_df_property(
		'host_title',
		'options',
		frm.hosts.map((host) => host.title)
	)
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

function is_active(doc) {
	return doc.expires_at && frappe.datetime.str_to_obj(doc.expires_at) > frappe.datetime.system_datetime(true)
}
