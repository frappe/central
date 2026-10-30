// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

const EMAILS = [
	{ value: "signup_code", label: __("Signup code") },
	{ value: "site_ready", label: __("Site ready") },
	{ value: "trial_unopened", label: __("Site not opened yet") },
	{ value: "trial_expiring", label: __("Trial ending soon") },
	{ value: "trial_ended", label: __("Trial ended") },
	{ value: "trial_deletion_soon", label: __("Site deleted soon") },
	{ value: "trial_converted", label: __("Trial converted") },
];

frappe.ui.form.on("Product", {
	refresh(frm) {
		if (frm.is_new() || !frm.has_perm("write")) return;

		if (frm.doc.enabled) {
			frm.add_custom_button(__("Open Signup Page"), () => {
				const product = encodeURIComponent(frm.doc.name);
				window.open(`/dashboard/signup?product=${product}`, "_blank", "noopener");
			});
		}

		frm.add_custom_button(__("Preview Email"), () => choose_email(frm, preview_email), __("Emails"));
		frm.add_custom_button(__("Send Test Email"), () => choose_email(frm, send_test_email), __("Emails"));

		// Regional images, sites and the report reach across every team, which only a System Manager may.
		if (frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Preview Trial Images"), () => choose_region(frm));
			frm.add_custom_button(__("Sites"), () => frappe.set_route("List", "Site", { product: frm.doc.name }), __("View"));
			frm.add_custom_button(__("Trial Sites Report"), () => frappe.set_route("query-report", "Trial Sites"), __("View"));
		}
	},
});

function choose_email(frm, action) {
	frappe.prompt(
		{
			fieldname: "event_type",
			fieldtype: "Select",
			label: __("Email"),
			options: EMAILS,
			default: "site_ready",
			reqd: 1,
		},
		({ event_type }) => action(frm, event_type),
		__("Choose an Email"),
	);
}

async function preview_email(frm, event_type) {
	// The form's unsaved changes go with the call, so a note can be checked before saving.
	const { message } = await frm.call({ doc: frm.doc, method: "preview_email", args: { event_type }, freeze: true });
	const dialog = new frappe.ui.Dialog({
		title: message.subject,
		size: "large",
		fields: [{ fieldname: "email", fieldtype: "HTML" }],
	});
	const frame = document.createElement("iframe");
	frame.setAttribute("sandbox", "");
	frame.style.cssText = "width: 100%; height: 560px; border: 0;";
	frame.srcdoc = message.html;
	dialog.fields_dict.email.$wrapper.empty().append(frame);
	dialog.show();
}

async function send_test_email(frm, event_type) {
	await frm.call({ doc: frm.doc, method: "send_test_email", args: { event_type }, freeze: true });
	frappe.show_alert({ message: __("Test email sent to {0}", [frappe.session.user]), indicator: "green" });
}

function choose_region(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the product before previewing its images."));
		return;
	}

	frappe.prompt(
		{ fieldname: "region", fieldtype: "Link", options: "Region", label: __("Region"), reqd: 1 },
		({ region }) => show_images(frm, region, 0),
		__("Preview Trial Images"),
	);
}

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
			: __("No {0} trial image has {1} installed in this region. Build one in Cargo.", [
					frm.doc.frappe_version,
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
