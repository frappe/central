frappe.listview_settings["Team"] = {
	get_indicator(doc) {
		const colors = { Active: "green", Suspended: "orange", Archived: "gray" };
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
