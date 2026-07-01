// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// Mirror of configurator._num / _vcpu_label / parse_vcpu, for live autofill.
const num = (v) => parseFloat(Number(v).toPrecision(12)).toString();
// "1/16" -> 0.0625, "4" -> 4 — start_vcpu is a fraction-string dropdown value.
function parse_vcpu(v) {
	if (v == null || v === "") return 0;
	const s = String(v).trim();
	if (s.includes("/")) {
		const [n, d] = s.split("/");
		return parseFloat(n) / parseFloat(d);
	}
	return parseFloat(s);
}
function vcpu_label(v) {
	if (v >= 1) return `${num(v)} vCPU`;
	const inv = 1 / v;
	return Math.abs(inv - Math.round(inv)) < 1e-6 ? `1/${Math.round(inv)} vCPU` : `${num(v)} vCPU`;
}

frappe.ui.form.on("Plan Configurator", {
	sub_category(frm) {
		if (!frm.doc.sub_category) return;
		// Pre-fill the memory ratio from the profile; the admin can override it after.
		frappe.db.get_value("Plan Sub-Category", frm.doc.sub_category, "memory_ratio").then((r) => {
			const ratio = r.message && r.message.memory_ratio;
			if (ratio) frm.set_value("memory_ratio", ratio);
		});
		if (!frm.doc.__user_set_prefix) frm.set_value("plan_name_prefix", frm.doc.sub_category);
	},

	plan_name_prefix(frm) {
		frm.doc.__user_set_prefix = true;
	},

	purpose(frm) {
		// Switching the template's job swaps which actions belong here — rebuild them.
		frm.clear_custom_buttons();
		frm.trigger("refresh");
	},

	refresh(frm) {
		// Sub-categories belong to a category; only offer this category's.
		frm.set_query("sub_category", () => ({ filters: { category: frm.doc.category } }));

		if (frm.is_new()) {
			frm.dashboard.set_headline(
				frm.doc.purpose === "Component Rate Card"
					? __("Save the template, then seed and apply the component rate card.")
					: __("Save the template, then populate and generate plans.")
			);
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

		// A template does one job (see `purpose`): author Plan Bundles OR maintain a
		// Component Rate Card. Show only that job's actions — never both at once. The
		// secondary steps live under one "Actions" menu, leaving a single primary button.
		if (frm.doc.purpose === "Component Rate Card") {
			bundle_card_actions(frm);
		} else {
			bundle_plan_actions(frm);
		}
	},

	category(frm) {
		// builder is fetched from the category; resections depend on it.
		frm.refresh_fields();
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
	if (!row.multiplier) row.multiplier = row.vcpu / (parse_vcpu(frm.doc.start_vcpu) || 1);
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

// Plan Bundles: author a ladder of sellable plans. Populate/Preview are the secondary
// steps (under "Actions"); Generate is the single primary once there are rows to ship.
function bundle_plan_actions(frm) {
	const simple = frm.doc.builder === "Simple";

	// The vCPU ladder builder authors plans from a formula; the simple builder
	// authors them row-by-row, so Populate/Preview are VM Rungs-only.
	if (!simple) {
		frm.add_custom_button(
			__("Populate Rungs"),
			() => {
				frm.call("populate_rungs").then((r) => {
					frappe.show_alert({
						message: __("{0} rungs populated — edit them, then Generate.", [
							(r.message || {}).count || 0,
						]),
						indicator: "blue",
					});
					frm.reload_doc();
				});
			},
			__("Actions")
		);

		frm.add_custom_button(
			__("Preview Pricing"),
			() => frm.call("preview").then((r) => show_preview(r.message || {})),
			__("Actions")
		);
	}

	const rows = simple ? frm.doc.simple_plans : frm.doc.rungs;
	if ((rows || []).length) {
		frm.add_custom_button(__("Generate Plans"), () => generate_dialog(frm)).addClass(
			"btn-primary"
		);
	}
}

// Component rate card (ADR 0011): the Configurator prices the composed-config primitives
// (Compute / Memory / Disk), so an incomplete card surfaces here — before a region can
// offer custom configs — not as a silent $0 estimate. Seed is the secondary step
// (under "Actions"); Apply is the single primary once there are rows.
function bundle_card_actions(frm) {
	frm.add_custom_button(
		__("Seed Component Rows"),
		() => {
			frm.call("seed_component_rows").then((r) => {
				frappe.show_alert({
					message: __("{0} component rows added.", [(r.message || {}).added || 0]),
					indicator: "blue",
				});
				frm.reload_doc();
			});
		},
		__("Actions")
	);
	if ((frm.doc.component_rates || []).length) {
		frm.add_custom_button(__("Apply Component Card"), () =>
			apply_component_card_dialog(frm)
		).addClass("btn-primary");
	}
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
				fieldtype: "Link",
				options: "Atlas Instance",
				label: __("Atlas Instance"),
				description: __("Blank = global rate (every Atlas Instance). Else pick one. Re-run per Atlas Instance."),
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
					frm.doc.builder === "Simple"
						? (frm.doc.simple_plans || []).map((p) => ({
								label: `${p.title}  ·  ${p.quantity || 0} ${p.unit || ""}${price_hint(
									p.multiplier || 1
								)}`,
								value: p.title,
								checked: 1,
						  }))
						: (frm.doc.rungs || []).map((p) => ({
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

function apply_component_card_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Apply Component Card"),
		fields: [
			{
				fieldname: "cluster",
				fieldtype: "Link",
				options: "Atlas Instance",
				label: __("Atlas Instance"),
				description: __("Blank = global rate (every Atlas Instance). Else price one region. Re-run per Atlas Instance."),
			},
		],
		primary_action_label: __("Apply"),
		primary_action(values) {
			frm.call("apply_component_card", { cluster: values.cluster }).then((r) => {
				d.hide();
				const res = r.message || {};
				const incomplete = res.incomplete || {};
				const gaps = Object.keys(incomplete);
				if (!gaps.length) {
					frappe.show_alert({
						message: __("Component card applied — every currency is complete for {0}.", [
							res.cluster || __("global"),
						]),
						indicator: "green",
					});
					return;
				}
				const rows = gaps
					.map(
						(c) =>
							`<li><b>${frappe.utils.escape_html(c)}</b>: ${__("missing")} ${incomplete[c]
								.map((rt) => frappe.utils.escape_html(rt))
								.join(", ")}</li>`
					)
					.join("");
				frappe.msgprint({
					title: __("Card applied — but incomplete for some currencies"),
					indicator: "orange",
					message:
						__("These currencies can't offer custom configs until every primitive is priced:") +
						`<ul>${rows}</ul>`,
				});
			});
		},
	});
	d.show();
}
