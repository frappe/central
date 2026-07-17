// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// The state field is an Autocomplete: for an Indian billing address we feed it
// the GST state list (so the value matches a code the server can validate the
// GSTIN against); for any other country we leave it as free text.
frappe.ui.form.on("Billing Profile", {
	refresh: (frm) => set_state_options(frm),
	country: (frm) => set_state_options(frm),
});

function set_state_options(frm) {
	if (frm.doc.country !== "India") {
		frm.set_df_property("state", "options", "");
		return;
	}
	frappe.xcall("central.billing.api.dashboard.account.get_billing_geo").then((geo) => {
		frm.set_df_property("state", "options", geo.india_states.join("\n"));
	});
}
