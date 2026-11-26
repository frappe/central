// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.listview_settings["Service"] = {
	add_fields: ["secret_delivery_status"],
	get_indicator(doc) {
		const colours = { Pending: "orange", Delivered: "green", Failed: "red" };
		if (doc.secret_delivery_status)
			return [
				__(doc.secret_delivery_status),
				colours[doc.secret_delivery_status],
				`secret_delivery_status,=,${doc.secret_delivery_status}`,
			];
	},
};
