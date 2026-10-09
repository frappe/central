// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["User Mail Account"] = {
	get_indicator(doc) {
		const colors = { Pending: "orange", Available: "green", Assigned: "blue", Removing: "orange", Deleted: "gray" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
