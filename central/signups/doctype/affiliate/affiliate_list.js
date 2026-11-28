frappe.listview_settings["Affiliate"] = {
	add_fields: ["status", "enabled"],
	get_indicator(doc) {
		if (!doc.enabled) {
			return [__("Disabled"), "red", "enabled,=,0"];
		}
		const colors = { Active: "green", Paused: "orange" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
