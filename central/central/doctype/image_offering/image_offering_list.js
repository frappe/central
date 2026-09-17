frappe.listview_settings["Image Offering"] = {
	add_fields: ["enabled"],
	get_indicator(doc) {
		return doc.enabled
			? [__("Enabled"), "green", "enabled,=,1"]
			: [__("Disabled"), "gray", "enabled,=,0"];
	},
};
