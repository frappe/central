// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Plan Configurator", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.dashboard.set_headline(__("Save the template, then generate plans."));
			return;
		}

		frm.add_custom_button(__("Preview Ladder"), () => {
			frm.call("preview").then((r) => show_preview(r.message || []));
		});

		frm.add_custom_button(__("Generate Plans"), () => {
			const where = frm.doc.default_cluster || __("global");
			frappe.confirm(
				__("Create the bundles for this ladder and price them for {0} ({1})?", [
					frm.doc.currency,
					where,
				]),
				() =>
					frm.call("generate").then((r) => {
						const m = r.message || {};
						frappe.msgprint({
							title: __("Plans Generated"),
							indicator: "green",
							message: __("{0} created, {1} skipped (already existed).", [
								(m.created || []).length,
								(m.skipped || []).length,
							]),
						});
						frm.reload_doc();
					})
			);
		}).addClass("btn-primary");

		if ((frm.doc.plans || []).length) {
			frm.add_custom_button(__("Apply Pricing to Cluster"), () => apply_dialog(frm));
		}
	},
});

function show_preview(rungs) {
	if (!rungs.length) {
		frappe.msgprint(__("Nothing to preview — check the sizing inputs."));
		return;
	}
	const rows = rungs
		.map(
			(r) => `<tr>
				<td>${frappe.utils.escape_html(r.label)}</td>
				<td class="text-right">${r.vcpu}</td>
				<td class="text-right">${r.memory_gb}</td>
				<td class="text-right">${r.disk_gb || "—"}</td>
				<td class="text-right">×${r.multiplier}</td>
				<td class="text-right">${format_currency(r.rate)}</td>
			</tr>`
		)
		.join("");
	frappe.msgprint({
		title: __("Ladder Preview — {0} sizes", [rungs.length]),
		message: `<table class="table table-bordered">
			<thead><tr>
				<th>${__("Size")}</th><th class="text-right">${__("vCPU")}</th>
				<th class="text-right">${__("GB")}</th><th class="text-right">${__("Disk")}</th>
				<th class="text-right">${__("Rate ×")}</th><th class="text-right">${__("Rate")}</th>
			</tr></thead><tbody>${rows}</tbody></table>`,
		wide: true,
	});
}

function apply_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Apply Pricing to Cluster"),
		fields: [
			{
				fieldname: "cluster",
				fieldtype: "Data",
				label: __("Cluster"),
				description: __("Blank = global (every cluster). Else a region key."),
			},
			{ fieldname: "cb", fieldtype: "Column Break" },
			{
				fieldname: "currency",
				fieldtype: "Link",
				label: __("Currency"),
				options: "Currency",
				default: frm.doc.currency,
				reqd: 1,
			},
			{
				fieldname: "base_rate",
				fieldtype: "Currency",
				label: __("Base Rate"),
				default: frm.doc.base_rate,
				reqd: 1,
				description: __("Smallest rung's price; scales by size."),
			},
			{ fieldname: "sb", fieldtype: "Section Break", label: __("Plans") },
			{
				fieldname: "plans",
				fieldtype: "MultiCheck",
				columns: 1,
				get_data: () =>
					(frm.doc.plans || []).map((p) => ({
						label: `${p.label}  (${p.plan})`,
						value: p.plan,
						checked: 1,
					})),
			},
		],
		primary_action_label: __("Apply Pricing"),
		primary_action(values) {
			const plans = values.plans || [];
			if (!plans.length) {
				frappe.msgprint(__("Select at least one plan."));
				return;
			}
			frm.call("apply_pricing_to_cluster", {
				cluster: values.cluster,
				currency: values.currency,
				base_rate: values.base_rate,
				plans: plans,
			}).then((r) => {
				const m = r.message || {};
				d.hide();
				frappe.msgprint({
					title: __("Pricing Applied"),
					indicator: "green",
					message: __("{0}: {1} priced, {2} updated.", [
						m.cluster || __("global"),
						(m.created || []).length,
						(m.updated || []).length,
					]),
				});
			});
		},
	});
	d.show();
}
