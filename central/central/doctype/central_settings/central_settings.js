// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Central Settings", {
	refresh(frm) {
		frm.add_custom_button(
			frm.doc.github_app_id ? __("Replace GitHub App") : __("Create GitHub App"),
			() => create_github_app(),
			__("GitHub")
		);
	},
});

function create_github_app() {
	new frappe.ui.Dialog({
		title: __("Create GitHub App"),
		fields: [
			{
				fieldname: "app_name",
				fieldtype: "Data",
				label: __("App Name"),
				reqd: 1,
				default: "Frappe Cloud",
				description: __("Must be unique on GitHub."),
			},
			{
				fieldname: "organization",
				fieldtype: "Data",
				label: __("GitHub Organization"),
				description: __("Leave empty to create the App on your personal account."),
			},
		],
		primary_action_label: __("Continue on GitHub"),
		primary_action({ app_name, organization }) {
			frappe
				.call("central.api.integrations.github.create_app_manifest", { app_name, organization })
				.then(({ message }) => {
					// GitHub takes the manifest only as a form post.
					$('<form method="post">')
						.attr("action", message.action)
						.append($('<input type="hidden" name="manifest">').val(message.manifest))
						.appendTo("body")
						.trigger("submit");
				});
		},
	}).show();
}
