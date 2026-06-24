// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Plan Configurator (issue #33): the Plan list's entry point routes straight to
// a new Plan Configurator document — author the ladder there (rungs, base rates,
// per-Atlas-Instance pricing) instead of the old one-off shortcut dialog.
frappe.listview_settings["Plan"] = {
	onload(listview) {
		listview.page.add_inner_button(__("New from Configurator"), () => {
			frappe.new_doc("Plan Configurator");
		});
	},
};
