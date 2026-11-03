// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["WireGuard Device"] = {
	get_indicator(doc) {
		const colors = { Active: "green", Removing: "orange" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
