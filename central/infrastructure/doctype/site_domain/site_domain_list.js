// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["Site Domain"] = {
	get_indicator(doc) {
		const colors = { Pending: "orange", Active: "green", Failed: "red" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
