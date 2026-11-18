frappe.listview_settings["App Rollout Hold"] = {
	get_indicator(doc) {
		if (doc.released) {
			return [__("Released"), "green", "released,=,1"];
		}
		return [__("Held"), "red", "released,=,0"];
	},
};
