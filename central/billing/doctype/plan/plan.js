// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Plan", {
	refresh(frm) {
		// Only offer sub-categories that belong to the chosen family (ADR 0007).
		frm.set_query("sub_category", () => ({
			filters: { category: frm.doc.category, is_active: 1 },
		}));
	},

	category(frm) {
		// Switching family invalidates a sub-category from the old one.
		if (frm.doc.sub_category) {
			frm.set_value("sub_category", null);
		}
	},
});
