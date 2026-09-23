frappe.ui.form.on("Image Offering", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

		frm.add_custom_button(__("Preview Regional Images"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the offering before previewing its images."));
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
				__("Preview Regional Images"),
			);
		});
	},
});

async function show_images(frm, region, offset) {
	const { message } = await frm.call({
		method: "preview_images",
		args: { region, offset },
		freeze: true,
	});
	const rows = message.items.map((image) =>
		`<li>${frappe.utils.escape_html(image.title)} (${frappe.utils.escape_html(image.architecture)})</li>`,
	).join("");

	const options = {
		title: __("Available Images"),
		message: rows ? `<ul>${rows}</ul>` : __("No available images on this page."),
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
