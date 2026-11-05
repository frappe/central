// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

const ADD_FROM_FILE = "central.infrastructure.doctype.metal_vpn_profile.metal_vpn_profile.add_from_file";

frappe.listview_settings["Metal VPN Profile"] = {
	get_indicator(doc) {
		const colors = { Available: "green", Assigned: "blue", Archived: "gray" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},

	primary_action() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add VPN Profile"),
			fields: [
				{ fieldname: "profile_name", fieldtype: "Data", label: __("Name"), reqd: 1 },
				{
					fieldname: "profile_file",
					fieldtype: "Attach",
					label: __("Profile File"),
					reqd: 1,
					options: { restrictions: { allowed_file_types: [".ovpn", ".conf", ".txt"] } },
				},
				{ fieldname: "usecase", fieldtype: "Data", label: __("Usecase") },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Add"),
			async primary_action(values) {
				const name = await frappe.xcall(ADD_FROM_FILE, {
					profile_name: values.profile_name,
					file_url: values.profile_file,
					usecase: values.usecase,
					note: values.note,
				});
				dialog.hide();
				frappe.set_route("Form", "Metal VPN Profile", name);
			},
		});
		dialog.show();
	},
};
