// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Plan Configurator (issue #33): a thin Desk entry point over the tested
// `create_configured_plan` API. Pick a ratio + vCPU, memory auto-fills (and is
// editable for off-ratio bundles), add disk — the server writes plain
// quantity/unit Plan Includes. Rates are authored separately (Catalog Rate).
frappe.listview_settings["Plan"] = {
	onload(listview) {
		listview.page.add_inner_button(__("New from Configurator"), () => {
			const factor = { "1:2": 2, "1:4": 4 };
			const dialog = new frappe.ui.Dialog({
				title: __("Plan Configurator"),
				fields: [
					{ fieldname: "name", label: __("Identity"), fieldtype: "Data", reqd: 1,
						description: __("Immutable bundle identity, e.g. bundle-2vcpu") },
					{ fieldname: "title", label: __("Title"), fieldtype: "Data", reqd: 1 },
					{ fieldname: "ratio", label: __("Memory Ratio"), fieldtype: "Select",
						options: ["1:2", "1:4"], default: "1:2", reqd: 1 },
					{ fieldname: "vcpu", label: __("vCPU"), fieldtype: "Float", reqd: 1,
						description: __("Fractional allowed: 0.125, 0.25, 0.5, 1, 2 …") },
					{ fieldname: "memory_gb", label: __("Memory (GB)"), fieldtype: "Float",
						description: __("Auto-filled from the ratio; edit for an off-ratio bundle") },
					{ fieldname: "disk_gb", label: __("Disk (GB)"), fieldtype: "Float", reqd: 1 },
				],
				primary_action_label: __("Create"),
				primary_action(values) {
					frappe.call({
						method: "billing.catalog.plans.create_configured_plan",
						args: values,
						callback: (r) => {
							if (r.message) {
								dialog.hide();
								frappe.set_route("Form", "Plan", r.message);
							}
						},
					});
				},
			});
			// Pre-fill memory from ratio × vCPU; the user can override afterwards.
			const prefill = () => {
				const v = dialog.get_value("vcpu");
				const f = factor[dialog.get_value("ratio")];
				if (v && f) dialog.set_value("memory_gb", v * f);
			};
			dialog.fields_dict.vcpu.df.onchange = prefill;
			dialog.fields_dict.ratio.df.onchange = prefill;
			dialog.show();
		});
	},
};
