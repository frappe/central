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

// Mirror of configurator._num / _vcpu_label, for live autofill of added rows.
const num = (v) => parseFloat(Number(v).toPrecision(12)).toString();
function vcpu_label(v) {
	if (v >= 1) return `${num(v)} vCPU`;
	const inv = 1 / v;
	return Math.abs(inv - Math.round(inv)) < 1e-6 ? `1/${Math.round(inv)} vCPU` : `${num(v)} vCPU`;
}

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

		// Background generation notifies the user who queued it.
		if (!frm.__pc_realtime) {
			frm.__pc_realtime = true;
			frappe.realtime.on("plan_configurator_done", (data) => {
				if (!data || data.configurator !== frm.doc.name) return;
				frappe.msgprint({
					title: __("Plans Generated"),
					indicator: "green",
					message: __("{0}: {1} created, {2} skipped.", [
						data.cluster,
						(data.created || []).length,
						(data.skipped || []).length,
					]),
				});
				frm.reload_doc();
			});
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
			frm.add_custom_button(__("Generate Plans"), () => generate_dialog(frm)).addClass(
				"btn-primary"
			);
		}
	},
});

// Live autofill for hand-added / edited rungs (the server also fills blanks on save).
frappe.ui.form.on("Plan Configurator Plan", {
	vcpu: (frm, cdt, cdn) => fill_rung(frm, locals[cdt][cdn]),
	memory_gb: (frm, cdt, cdn) => fill_rung(frm, locals[cdt][cdn]),
});

function fill_rung(frm, row) {
	if (!row.vcpu || !row.memory_gb) return;
	const prefix = frm.doc.plan_name_prefix || "Bundle";
	if (!row.plan_name) row.plan_name = `${prefix} ${num(row.vcpu)} vCPU ${num(row.memory_gb)} GB`;
	if (!row.label) row.label = `${vcpu_label(row.vcpu)} · ${num(row.memory_gb)} GB`;
	if (!row.multiplier) row.multiplier = row.vcpu / (frm.doc.start_vcpu || 1);
	frm.refresh_field("rungs");
}

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

function generate_dialog(frm) {
	const base = frm.doc.base_rates || [];
	const primary = base[0];
	const price_hint = (mult) =>
		primary ? ` — ${format_currency(primary.base_rate * mult, primary.currency)}` : "";

	const d = new frappe.ui.Dialog({
		title: __("Generate Plans"),
		size: "large",
		fields: [
			{
				fieldname: "cluster",
				fieldtype: "Data",
				label: __("Cluster"),
				description: __("Blank = global rate (every cluster). Else a region key. Re-run per cluster."),
			},
			{ fieldname: "sb_cur", fieldtype: "Section Break", label: __("Currencies") },
			{
				fieldname: "currencies",
				fieldtype: "MultiCheck",
				columns: 3,
				get_data: () => base.map((r) => ({ label: r.currency, value: r.currency, checked: 1 })),
			},
			{ fieldname: "sb_plans", fieldtype: "Section Break", label: __("Plans to generate") },
			{
				fieldname: "plans",
				fieldtype: "MultiCheck",
				columns: 1,
				get_data: () =>
					(frm.doc.rungs || []).map((p) => ({
						label: `${p.label || p.plan_name}  ·  ${p.disk_gb || 0} GB disk · ${
							p.transfer_gb || 0
						} GB xfer${price_hint(p.multiplier)}`,
						value: p.plan_name,
						checked: 1,
					})),
			},
		],
		primary_action_label: __("Generate in Background"),
		primary_action(values) {
			if (!(values.plans || []).length) return frappe.msgprint(__("Select at least one plan."));
			if (!(values.currencies || []).length)
				return frappe.msgprint(__("Select at least one currency."));
			frm.call("enqueue_generation", {
				cluster: values.cluster,
				currencies: values.currencies,
				plans: values.plans,
			}).then(() => {
				d.hide();
				frappe.show_alert({
					message: __("Queued — generating {0} plans for {1}.", [
						values.plans.length,
						values.cluster || __("global"),
					]),
					indicator: "blue",
				});
			});
		},
	});
	d.show();
}
