// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// The state field is an Autocomplete: for an Indian billing address we feed it
// the GST state list (so the value matches a code the server can validate the
// GSTIN against); for any other country we leave it as free text.
frappe.ui.form.on("Billing Profile", {
	refresh: (frm) => {
		set_state_options(frm);
		add_clear_setup_lock(frm);
	},
	country: (frm) => set_state_options(frm),
});

// Shown only while the team must wait after too many failed setups or top-ups.
function add_clear_setup_lock(frm) {
	if (!frm.doc.__onload?.setup_lock_wait) return;
	frm.add_custom_button(__("Clear Setup Lock"), () =>
		frappe.confirm(
			__("Let this team add a payment method or top up again now?"),
			() =>
				frappe
					.call({
						method: "central.billing.api.admin.teams.clear_setup_lock",
						args: { team: frm.doc.name },
						freeze: true,
					})
					.then(() => {
						frappe.show_alert({ message: __("Setup lock cleared"), indicator: "green" });
						frm.reload_doc();
					})
		)
	);
}

function set_state_options(frm) {
	if (frm.doc.country !== "India") {
		frm.set_df_property("state", "options", "");
		return;
	}
	frappe.xcall("central.billing.api.dashboard.account.get_billing_geo").then((geo) => {
		frm.set_df_property("state", "options", geo.india_states.join("\n"));
	});
}
