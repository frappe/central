// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["VM Snapshot"] = {
	get_indicator(doc) {
		const colors = { Pending: "orange", Available: "green", Failed: "red", Deleted: "gray" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
