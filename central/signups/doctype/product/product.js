// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Product", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

		if (frm.doc.enabled) {
			frm.add_custom_button(__("Open Signup Page"), () => {
				const product = encodeURIComponent(frm.doc.name);
				window.open(`/dashboard/signup?product=${product}`, "_blank", "noopener");
			});
		}

		frm.add_custom_button(__("Preview Trial Images"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the product before previewing its images."));
				return;
			}

			frappe.prompt(
				{
					fieldname: "region",
					fieldtype: "Link",
					options: "Region",
					label: __("Region"),
					reqd: 1,
				},
				({ region }) => show_images(frm, region, 0),
				__("Preview Trial Images"),
			);
		});
	},
});

async function show_images(frm, region, offset) {
	const { message } = await frm.call({
		doc: frm.doc,
		method: "preview_images",
		args: { region, offset },
		freeze: true,
	});
	const rows = message.items
		.map(
			(image) =>
				`<li>${frappe.utils.escape_html(image.title)} (${frappe.utils.escape_html(image.tags[`app_${frm.doc.signup_app}`] || "")})</li>`,
		)
		.join("");

	const options = {
		title: __("Trial Images for {0}", [frm.doc.title]),
		message: rows
			? `<ul>${rows}</ul>`
			: __("No trial image has {0} installed in this region. Build one in Cargo.", [
					frm.doc.signup_app,
				]),
	};
	if (message.next_offset !== null) {
		options.primary_action = {
			label: __("Next Page"),
			action() {
				frappe.hide_msgprint();
				show_images(frm, region, message.next_offset);
			},
		};
	}

	frappe.msgprint(options);
}
