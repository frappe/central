// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Plan classes pin the memory ratio the way cloud families do (mirror of
// configurator.CLASS_RATIOS).
const CLASS_RATIOS = {
	"CPU Optimised": "1:2",
	General: "1:4",
	"Memory Optimised": "1:8",
	"Storage Optimised": "1:8",
};

frappe.ui.form.on("Plan Configurator", {
	plan_class(frm) {
		const ratio = CLASS_RATIOS[frm.doc.plan_class];
		if (ratio) frm.set_value("memory_ratio", ratio);
		if (frm.doc.plan_class && frm.doc.plan_class !== "Custom" && !frm.doc.__user_set_prefix) {
			frm.set_value("plan_name_prefix", frm.doc.plan_class);
		}
	},

	plan_name_prefix(frm) {
		frm.doc.__user_set_prefix = true;
	},

	refresh(frm) {
		if (frm.is_new()) {
			frm.dashboard.set_headline(__("Save the template, then populate and generate rungs."));
			return;
		}

		frm.add_custom_button(__("Populate Rungs"), () => {
			frm.call("populate_rungs").then((r) => {
				frappe.show_alert({
					message: __("{0} rungs populated — edit them, then Generate.", [
						(r.message || {}).count || 0,
					]),
					indicator: "blue",
				});
				frm.reload_doc();
			});
		});

		frm.add_custom_button(__("Preview Pricing"), () => {
			frm.call("preview").then((r) => show_preview(r.message || {}));
		});

		if ((frm.doc.rungs || []).length) {
			frm.add_custom_button(__("Generate Plans"), () => {
				const where = frm.doc.default_cluster || __("global");
				frappe.confirm(
					__("Create {0} bundles and price them ({1} currencies, {2})?", [
						frm.doc.rungs.length,
						(frm.doc.base_rates || []).length,
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

			frm.add_custom_button(__("Apply Pricing to Cluster"), () => apply_dialog(frm));
		}
	},
});

function show_preview(data) {
	const rungs = data.rungs || [];
	const currencies = data.currencies || [];
	if (!rungs.length) {
		frappe.msgprint(__("Nothing to preview — set the sizing inputs (or populate rungs)."));
		return;
	}
	const rate_of = (rung, cur) => {
		const hit = (rung.rates || []).find((x) => x.currency === cur);
		return hit ? format_currency(hit.rate, cur) : "—";
	};
	const head =
		`<th>${__("Size")}</th><th class="text-right">${__("vCPU")}</th>` +
		`<th class="text-right">${__("RAM")}</th><th class="text-right">${__("Disk")}</th>` +
		`<th class="text-right">${__("Transfer")}</th>` +
		currencies.map((c) => `<th class="text-right">${frappe.utils.escape_html(c)}</th>`).join("");
	const body = rungs
		.map(
			(r) => `<tr>
				<td>${frappe.utils.escape_html(r.label || r.plan_name)}</td>
				<td class="text-right">${r.vcpu}</td>
				<td class="text-right">${r.memory_gb} GB</td>
				<td class="text-right">${r.disk_gb ? r.disk_gb + " GB" : "—"}</td>
				<td class="text-right">${r.transfer_gb ? r.transfer_gb + " GB" : "—"}</td>
				${currencies.map((c) => `<td class="text-right">${rate_of(r, c)}</td>`).join("")}
			</tr>`
		)
		.join("");
	frappe.msgprint({
		title: __("Pricing Preview — {0} rungs", [rungs.length]),
		message: `<table class="table table-bordered"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`,
		wide: true,
	});
}

function apply_dialog(frm) {
	const currencies = (frm.doc.base_rates || []).map((r) => r.currency);
	const d = new frappe.ui.Dialog({
		title: __("Apply Pricing to Cluster"),
		fields: [
			{
				fieldname: "cluster",
				fieldtype: "Data",
				label: __("Cluster"),
				description: __("Blank = global (every cluster). Else a region key."),
			},
			{ fieldname: "sb_cur", fieldtype: "Section Break", label: __("Currencies") },
			{
				fieldname: "currencies",
				fieldtype: "MultiCheck",
				columns: 2,
				get_data: () => currencies.map((c) => ({ label: c, value: c, checked: 1 })),
			},
			{ fieldname: "sb_plans", fieldtype: "Section Break", label: __("Plans") },
			{
				fieldname: "plans",
				fieldtype: "MultiCheck",
				columns: 1,
				get_data: () =>
					(frm.doc.rungs || []).map((p) => ({
						label: `${p.label || p.plan_name}  (${p.plan_name})`,
						value: p.plan_name,
						checked: 1,
					})),
			},
		],
		primary_action_label: __("Apply Pricing"),
		primary_action(values) {
			if (!(values.plans || []).length) return frappe.msgprint(__("Select at least one plan."));
			if (!(values.currencies || []).length)
				return frappe.msgprint(__("Select at least one currency."));
			frm.call("apply_pricing_to_cluster", {
				cluster: values.cluster,
				currencies: values.currencies,
				plans: values.plans,
			}).then((r) => {
				const results = r.message || [];
				const priced = results.reduce((n, x) => n + (x.created || []).length, 0);
				const updated = results.reduce((n, x) => n + (x.updated || []).length, 0);
				d.hide();
				frappe.msgprint({
					title: __("Pricing Applied"),
					indicator: "green",
					message: __("{0}: {1} priced, {2} updated across {3} currencies.", [
						values.cluster || __("global"),
						priced,
						updated,
						(values.currencies || []).length,
					]),
				});
			});
		},
	});
	d.show();
}
