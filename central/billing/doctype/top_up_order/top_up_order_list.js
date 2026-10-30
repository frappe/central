// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["Top-up Order"] = {
	get_indicator(doc) {
		const colours = { Created: "orange", Credited: "green", Failed: "red", Expired: "gray" };
		return [__(doc.status), colours[doc.status], `status,=,${doc.status}`];
	},
};
