// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

// The operator's window onto a projection: what this team will be billed, and what
// happens next whether or not they pay.
//
// Plain Desk — vanilla JS and jQuery, styled through Desk's own CSS variables. This is
// not the customer dashboard, so there is no frappe-ui here and there cannot be: that
// is a Vue library and a Desk page has no Vue.

frappe.pages["billing-simulator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Billing simulator"),
		single_column: true,
	});
	wrapper.simulator = new BillingSimulator(page);
};

class BillingSimulator {
	constructor(page) {
		this.page = page;
		this.add_filters();
		this.add_styles();
		this.$body = $('<div class="billing-simulator"></div>').appendTo(this.page.main);
		this.show_empty(__("Pick a team to project."));
	}

	add_filters() {
		this.team = this.page.add_field({
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
			reqd: 1,
			change: () => this.refresh(),
		});
		this.period = this.page.add_field({
			fieldname: "period_start",
			label: __("Period starting"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			change: () => this.refresh(),
		});
		this.months = this.page.add_field({
			fieldname: "months",
			label: __("Months"),
			fieldtype: "Select",
			options: ["1", "3", "6", "12"],
			default: "1",
			change: () => this.refresh(),
		});
		this.mode = this.page.add_field({
			fieldname: "mode",
			label: __("Outcomes"),
			fieldtype: "Select",
			options: ["Derived", "Optimistic", "Assumed"],
			default: "Derived",
			change: () => this.refresh(),
		});
		this.scenario = this.page.add_field({
			fieldname: "scenario",
			label: __("Scenario"),
			fieldtype: "Link",
			options: "Billing Scenario",
			change: () => this.apply_scenario(),
		});
		this.page.set_primary_action(__("Project"), () => this.refresh());
		this.page.add_menu_item(__("Save as scenario"), () => this.save_scenario());
		this.page.add_inner_button(__("Try a question"), () => this.pick_from_library());
	}

	// A saved scenario drives the projection itself: its overrides are read *instead of*
	// Billing Settings for the length of the call, which is why it cannot just be
	// unpacked into these filters.
	apply_scenario() {
		const name = this.scenario.get_value();
		if (!name) return this.refresh();

		// Reflecting the scenario's team back into the picker fires that field's own
		// change handler, which would kick off a plain refresh and overwrite the very
		// projection we are waiting for — with the default period, silently.
		this.applying = true;
		this.show_empty(__("Projecting…"));
		// Compare rather than project: a scenario's whole point is the difference it
		// makes, and the difference needs the unaltered projection to sit beside.
		frappe
			.call({
				method: "central.billing.api.admin.projection.compare_scenario",
				args: { scenario: name },
			})
			.then((r) => {
				if (!r.message) return;
				const comparison = r.message;
				const out = comparison.altered;
				out.repricing = comparison.repricing || out.repricing;
				out.explanation = comparison.explanation;
				this.team.set_value(out.team);
				if (out.scenario && out.scenario.months > 1) this.render_months(out);
				else this.render(out);
				if (out.repricing) this.$body.prepend(this.repricing_card(out));
				if (out.scenario) this.$body.prepend(this.pretending_card(out.scenario));
			})
			.catch(() => this.show_empty(__("Could not project this scenario.")))
			.finally(() => {
				this.applying = false;
			});
	}

	// A projection under an altered configuration that does not say so is a number
	// waiting to be quoted as fact.
	pretending_card(scenario) {
		const overrides = Object.entries(scenario.overrides || {});
		if (!overrides.length) return $();
		const items = overrides
			.map(
				([field, value]) =>
					`<li class="bs-finding"><span class="bs-finding-summary">${frappe.utils.escape_html(
						frappe.unscrub(field)
					)}</span><span class="bs-muted">${frappe.utils.escape_html(
						String(value)
					)} ${__("instead of what is configured")}</span></li>`
			)
			.join("");
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Projected under {0}", [
						frappe.utils.escape_html(scenario.scenario_name || scenario.name),
					])}</span>
					<span class="bs-muted">${__("Billing Settings are unchanged")}</span>
				</div>
				<ul class="bs-findings">${items}</ul>
			</div>`);
	}

	// The answer everyone expects to be a multiplication. Showing the two sides is the
	// only way a zero reads as a finding rather than a bug.
	repricing_card(out) {
		const r = out.repricing;
		const money = (v) => format_currency(v, r.currency);
		const delta = r.delta === undefined ? null : r.delta;

		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("How this bill is priced")}</span>
					<span class="bs-muted">${__("Effective {0}", [r.effective_from || "—"])}</span>
				</div>
				<table class="bs-table">
					<thead>
						<tr>
							<th>${__("Priced")}</th>
							<th class="bs-right">${__("Amount")}</th>
							<th class="bs-right">${__("Resources")}</th>
							<th>${__("Moves when")}</th>
						</tr>
					</thead>
					<tbody>
						<tr>
							<td>${__("Grandfathered")}</td>
							<td class="bs-right">${money(r.grandfathered)}</td>
							<td class="bs-right">${r.grandfathered_resources}</td>
							<td class="bs-muted">${__("the resource is resized or replaced")}</td>
						</tr>
						<tr>
							<td>${__("Repriced")}</td>
							<td class="bs-right ${r.repriced ? "bs-short" : ""}">${money(r.repriced)}</td>
							<td class="bs-right">${r.repriced_resources}</td>
							<td class="bs-muted">${__("immediately — priced from today's catalog")}</td>
						</tr>
					</tbody>
				</table>
				<div class="bs-totals">
					<div class="bs-total bs-grand"><span>${__("What this change does")}</span><span>${
						delta === null ? "—" : money(delta)
					}</span></div>
					${
						out.explanation
							? `<p class="bs-muted" style="margin:8px 0 0; line-height:1.55; max-width:74ch">${frappe.utils.escape_html(
									out.explanation
							  )}</p>`
							: ""
					}
				</div>
			</div>`);
	}

	// The shelf of canned questions. Each one says what it asks and what to look for,
	// because a button with no explanation is one nobody presses twice.
	pick_from_library() {
		const team = this.team.get_value();
		if (!team) {
			frappe.show_alert({ message: __("Pick a team first."), indicator: "orange" });
			return;
		}

		frappe
			.call({ method: "central.billing.api.admin.projection.scenario_library" })
			.then((r) => {
				const entries = r.message || [];
				const dialog = new frappe.ui.Dialog({
					title: __("Try a question"),
					fields: [
						{
							fieldname: "key",
							label: __("Question"),
							fieldtype: "Select",
							reqd: 1,
							options: entries.map((e) => ({ label: e.title, value: e.key })),
							change() {
								const chosen = entries.find((e) => e.key === this.get_value());
								dialog.set_df_property(
									"about",
									"options",
									chosen
										? `<div class="text-muted"><p>${frappe.utils.escape_html(
												chosen.question
										  )}</p><p><b>${__("Look for")}:</b> ${frappe.utils.escape_html(
												chosen.look_for
										  )}</p></div>`
										: ""
								);
							},
						},
						{ fieldname: "about", fieldtype: "HTML" },
					],
					primary_action_label: __("Project it"),
					primary_action: ({ key }) => {
						dialog.hide();
						this.run_library_scenario(key, team);
					},
				});
				dialog.show();
			});
	}

	run_library_scenario(key, team) {
		this.applying = true;
		this.show_empty(__("Projecting…"));
		frappe
			.call({
				method: "central.billing.api.admin.projection.project_from_library",
				args: { key, team, period_start: this.period.get_value() },
			})
			.then((r) => {
				if (!r.message) return;
				const out = r.message;
				if (out.scenario && out.scenario.months > 1) this.render_months(out);
				else this.render(out);
				if (out.library) this.$body.prepend(this.library_card(out.library));
			})
			.catch((e) => {
				// A scenario that cannot apply to this team says why rather than
				// projecting something misleading.
				this.show_empty(
					(e && e.message) || __("This question does not apply to that team.")
				);
			})
			.finally(() => {
				this.applying = false;
			});
	}

	library_card(entry) {
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${frappe.utils.escape_html(entry.title)}</span>
					<span class="bs-muted">${frappe.utils.escape_html(entry.question)}</span>
				</div>
				<div class="bs-note">${__("Look for")}: ${frappe.utils.escape_html(entry.look_for)}</div>
			</div>`);
	}

	save_scenario() {
		const team = this.team.get_value();
		if (!team) {
			frappe.show_alert({ message: __("Pick a team first."), indicator: "orange" });
			return;
		}
		const doc = frappe.model.get_new_doc("Billing Scenario");
		doc.team = team;
		doc.period_start = this.period.get_value();
		doc.months = cint(this.months.get_value()) || 1;
		doc.outcome_mode = this.mode.get_value() || "Derived";
		frappe.set_route("Form", "Billing Scenario", doc.name);
	}

	refresh() {
		if (this.applying) return;
		const team = this.team.get_value();
		if (!team) return;

		const start = this.period.get_value() || frappe.datetime.month_start();
		const months = cint(this.months.get_value()) || 1;
		const mode = this.mode.get_value() || "Derived";
		this.show_empty(__("Projecting…"));

		// One month is the detailed view; several is the roll-forward, where what each
		// month leaves behind is the whole point.
		const single = months === 1;
		frappe
			.call({
				method: single
					? "central.billing.api.admin.projection.project_team"
					: "central.billing.api.admin.projection.project_team_months",
				args: single
					? { team, period_start: start, mode }
					: { team, start, months, mode },
			})
			.then((r) => {
				if (!r.message) return;
				return single ? this.render(r.message) : this.render_months(r.message);
			})
			.catch(() => this.show_empty(__("Could not project this team.")));
	}

	show_empty(message) {
		this.$body.html(`<div class="bs-empty">${frappe.utils.escape_html(message)}</div>`);
	}

	render(data) {
		this.$body.empty();
		this.$body.append(this.invoice_card(data));
		if (data.refused && data.refused.length) this.$body.append(this.refused_card(data.refused));
		if (data.injected_events && data.injected_events.length) {
			this.$body.append(this.injected_card(data.injected_events));
		}
		if (data.outcome) this.$body.append(this.findings_card(data.outcome));
		this.$body.append(this.calendar_card(data.calendar, data.outcome));
		if (data.in_flight && data.in_flight.length) {
			this.$body.append(this.in_flight_card(data.in_flight, data.as_of));
		}
	}

	render_months(data) {
		this.$body.empty();
		this.$body.append(this.trajectory_card(data));
		if (data.events && data.events.length) {
			this.$body.append(this.events_card(data.events));
		}
	}

	// ---- the roll-forward --------------------------------------------------

	trajectory_card(data) {
		const money = (v) => format_currency(v, data.currency);
		const rows = data.months
			.map((m) => {
				if (m.suspended) {
					return `<tr class="bs-stopped">
						<td>${m.period_start}</td>
						<td colspan="4">${__("Suspended — nothing accrues")}</td>
					</tr>`;
				}
				const s = m.settlement || {};
				const short = s.shortfall > 0;
				return `<tr>
					<td>${m.period_start}</td>
					<td class="bs-right">${m.invoice ? money(m.invoice.total) : "—"}</td>
					<td class="bs-right">${s.from_credits != null ? money(s.from_credits) : "—"}</td>
					<td class="bs-right ${short ? "bs-short" : ""}">${
						short ? money(s.shortfall) : "—"
					}</td>
					<td class="bs-right">${m.balance_after != null ? money(m.balance_after) : "—"}</td>
				</tr>`;
			})
			.join("");

		const ends = data.ends || {};
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Month by month")}</span>
					<span class="bs-muted">${__(
						"Each month settles against what the ones before it left"
					)}</span>
				</div>
				<table class="bs-table">
					<thead>
						<tr>
							<th>${__("Month")}</th>
							<th class="bs-right">${__("Billed")}</th>
							<th class="bs-right">${__("From credits")}</th>
							<th class="bs-right">${__("Shortfall")}</th>
							<th class="bs-right">${__("Balance after")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
				<div class="bs-totals">
					<div class="bs-total"><span>${__("Ends with")}</span><span>${money(
						ends.balance || 0
					)}</span></div>
					<div class="bs-total"><span>${__("Standing")}</span><span>${frappe.utils.escape_html(
						ends.standing || "Current"
					)}</span></div>
					${
						ends.suspended_on
							? `<div class="bs-total"><span>${__(
									"Suspends on"
							  )}</span><span>${ends.suspended_on}</span></div>`
							: ""
					}
				</div>
			</div>`);
	}

	events_card(events) {
		const rows = events
			.map(
				(e) => `<li class="bs-finding">
					<span class="bs-finding-summary">${frappe.utils.escape_html(e.event)} · ${e.date}</span>
					${e.amount ? `<span class="bs-muted">${e.amount}</span>` : ""}
				</li>`
			)
			.join("");
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Along the way")}</span>
				</div>
				<ul class="bs-findings">${rows}</ul>
			</div>`);
	}

	// ---- projected invoice -------------------------------------------------

	invoice_card(data) {
		const invoice = data.invoice;
		if (!invoice) {
			return $(`<div class="bs-card"><div class="bs-empty">${__(
				"Nothing billable in this period."
			)}</div></div>`);
		}

		const money = (v) => format_currency(v, data.currency);
		const rows = invoice.lines
			.map(
				(line, i) => `
			<tr class="bs-line" data-line="${i}">
				<td>${line.derivation ? '<span class="bs-caret">▸</span>' : ""}${frappe.utils.escape_html(
					line.plan || line.resource_type || "—"
				)}</td>
				<td class="bs-muted">${frappe.utils.escape_html(describe_line(line))}</td>
				<td class="bs-right">${money(line.amount)}</td>
				<td>${basis_tag(line)}</td>
			</tr>
			<tr class="bs-why" data-why="${i}" hidden>
				<td colspan="4">${derivation_html(line, money)}</td>
			</tr>`
			)
			.join("");

		// A total is never shown on its own when part of it was inferred — a bill that
		// is half guesswork must not read like a bill.
		// Every basis present gets a row. A split that does not add up to the total is
		// worse than no split — it invites the reader to trust the total and ignore it.
		const split = invoice.has_estimates
			? [
					["Measured", invoice.measured],
					["Estimated", invoice.estimated],
					["Assumed", invoice.assumed],
			  ]
					.filter(([, amount]) => amount)
					.map(
						([label, amount]) =>
							`<div class="bs-total"><span>${__(label)}</span><span>${money(
								amount
							)}</span></div>`
					)
					.join("")
			: "";

		const tax = invoice.output_tax_amount
			? `<div class="bs-total"><span>${frappe.utils.escape_html(
					invoice.output_tax_type
			  )} @ ${invoice.output_tax_rate}%</span><span>${money(
					invoice.output_tax_amount
			  )}</span></div>`
			: "";

		const $card = $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Projected invoice")}</span>
					<span class="bs-muted">${data.period_start} — ${data.period_end} · ${__(
						"not yet issued"
					)}</span>
				</div>
				<table class="bs-table">
					<thead>
						<tr>
							<th>${__("Line")}</th><th>${__("Detail")}</th>
							<th class="bs-right">${__("Amount")}</th><th>${__("Basis")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
				<div class="bs-totals">
					${split}${tax}
					<div class="bs-total bs-grand"><span>${__("Projected total")}</span><span>${money(
						invoice.total
					)}</span></div>
				</div>
			</div>`);

		$card.on("click", ".bs-line", function () {
			const i = $(this).data("line");
			const $why = $card.find(`[data-why="${i}"]`);
			if (!$why.length) return;
			const open = !$why.prop("hidden");
			$why.prop("hidden", open);
			$(this).find(".bs-caret").text(open ? "▸" : "▾");
		});
		return $card;
	}

	// ---- things somebody invented ------------------------------------------

	injected_card(events) {
		const rows = events
			.map(
				(e) => `<tr>
					<td>${e.date}</td>
					<td>${frappe.utils.escape_html(e.event)}</td>
					<td class="bs-muted">${frappe.utils.escape_html(e.detail || "")}</td>
				</tr>`
			)
			.join("");
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Assumed to happen")}</span>
					<span class="bs-muted">${__("None of this is history")}</span>
				</div>
				<table class="bs-table">
					<thead><tr><th>${__("When")}</th><th>${__("What")}</th><th>${__("Detail")}</th></tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>`);
	}

	refused_card(refused) {
		// A scenario that could not happen is a finding, not a projection.
		const items = refused
			.map(
				(r) => `<li class="bs-finding">
					<span class="bs-finding-summary">${frappe.utils.escape_html(r.event)} ${
						r.on_date
					} — ${frappe.utils.escape_html(r.reason)}</span>
					<span class="bs-muted">${frappe.utils.escape_html(r.detail || "")}</span>
				</li>`
			)
			.join("");
		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("This could not happen")}</span>
					<span class="bs-muted">${__("The platform would refuse it")}</span>
				</div>
				<ul class="bs-findings">${items}</ul>
			</div>`);
	}

	// ---- what the state already decides ------------------------------------

	findings_card(outcome) {
		// Derived mode with nothing to report is a real answer, not an empty state: the
		// data does not settle whether the charge works, and saying so is the honest
		// alternative to implying success.
		if (outcome.mode !== "Derived") {
			return $(`<div class="bs-card"><div class="bs-note">${__(
				"Outcome is {0}, not derived from this team's state.",
				[outcome.mode.toLowerCase()]
			)}</div></div>`);
		}

		if (!outcome.findings.length) {
			return $(`<div class="bs-card"><div class="bs-note bs-note-ok">${__(
				"Nothing in this team's setup stops the charge. Whether it succeeds is not knowable from here."
			)}</div></div>`);
		}

		const items = outcome.findings
			.map(
				(f) => `<li class="bs-finding">
					<span class="bs-finding-summary">${frappe.utils.escape_html(f.summary)}</span>
					<span class="bs-muted">${frappe.utils.escape_html(f.detail)}</span>
				</li>`
			)
			.join("");

		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Why this will not settle")}</span>
					<span class="bs-muted">${__("Entailed by the team's state, not predicted")}</span>
				</div>
				<ul class="bs-findings">${items}</ul>
			</div>`);
	}

	// ---- the fork ----------------------------------------------------------

	calendar_card(calendar, outcome) {
		const $card = $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("What happens next")}</span>
					<span class="bs-muted">${__("Opens")} ${calendar.opens_on} · ${__("due")} ${
						calendar.due_on
					}</span>
				</div>
				<div class="bs-figure"></div>
			</div>`);
		$card.find(".bs-figure").append(timeline_svg(calendar, outcome));
		return $card;
	}

	// ---- invoices already unpaid -------------------------------------------

	in_flight_card(flights, as_of) {
		const rows = flights
			.map((f) => {
				const next = (f.ladder || []).find((s) => s.date > as_of);
				return `
				<tr>
					<td><a href="/desk/invoice/${encodeURIComponent(f.invoice)}">${frappe.utils.escape_html(
						f.invoice
					)}</a></td>
					<td>${frappe.utils.escape_html(f.status)}</td>
					<td class="bs-right">${format_currency(f.outstanding, f.currency)}</td>
					<td>${f.due_date}</td>
					<td>${f.clock_starts_on}${
						f.clock_deferred
							? ` <span class="bs-muted">(${__("deferred")})</span>`
							: ""
					}</td>
					<td>${next ? `${next.stage} · ${next.date}` : "—"}</td>
				</tr>`;
			})
			.join("");

		return $(`
			<div class="bs-card">
				<div class="bs-card-head">
					<span class="bs-card-title">${__("Already unpaid")}</span>
					<span class="bs-muted">${__(
						"A deferred clock means we failed to collect, so their escalation starts later."
					)}</span>
				</div>
				<table class="bs-table">
					<thead>
						<tr>
							<th>${__("Invoice")}</th><th>${__("Status")}</th>
							<th class="bs-right">${__("Outstanding")}</th><th>${__("Due")}</th>
							<th>${__("Clock starts")}</th><th>${__("Next action")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			</div>`);
	}

	add_styles() {
		if (document.getElementById("billing-simulator-styles")) return;
		$(`<style id="billing-simulator-styles">
			.billing-simulator { padding: 0 0 40px; }
			.bs-card { border: 1px solid var(--border-color); border-radius: var(--border-radius-md, 8px);
				background: var(--card-bg); margin-bottom: 14px; overflow: hidden; }
			.bs-card-head { display: flex; justify-content: space-between; align-items: center;
				gap: 12px; padding: 10px 13px; border-bottom: 1px solid var(--border-color); }
			.bs-card-title { font-weight: 600; color: var(--heading-color); }
			.bs-muted { color: var(--text-muted); font-size: var(--text-sm, 12px); }
			.bs-empty { padding: 28px 14px; text-align: center; color: var(--text-muted); }
			.bs-table { width: 100%; border-collapse: collapse; font-size: var(--text-base, 13px); }
			.bs-table th { text-align: left; font-weight: 500; color: var(--text-light);
				padding: 8px 13px; background: var(--subtle-accent);
				border-bottom: 1px solid var(--border-color); white-space: nowrap; }
			.bs-table td { padding: 8px 13px; border-bottom: 1px solid var(--border-color);
				vertical-align: middle; }
			.bs-table tbody tr:last-child td { border-bottom: 0; }
			.bs-right { text-align: right; font-variant-numeric: tabular-nums; }
			.bs-totals { padding: 10px 13px; }
			.bs-total { display: flex; justify-content: space-between; padding: 4px 0;
				font-size: var(--text-base, 13px); font-variant-numeric: tabular-nums; }
			.bs-grand { border-top: 1px solid var(--dark-border-color); margin-top: 5px;
				padding-top: 8px; font-weight: 600; color: var(--heading-color); }
			.bs-basis { display: inline-flex; align-items: center; gap: 6px;
				color: var(--text-light); font-size: var(--text-sm, 12px); }
			.bs-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
			.bs-dot-measured { background: var(--text-light); }
			.bs-dot-estimated { background: var(--card-bg); border: 1.5px solid var(--gray-400, #c7c7c7); }
			.bs-note { padding: 14px 13px; color: var(--text-light);
				font-size: var(--text-base, 13px); }
			.bs-note-ok { border-left: 2px solid var(--green-500, #59ba8b); }
			.bs-findings { list-style: none; margin: 0; padding: 0; }
			.bs-finding { padding: 10px 13px; border-bottom: 1px solid var(--border-color);
				border-left: 2px solid var(--red-500, #e03636); display: flex;
				flex-direction: column; gap: 2px; }
			.bs-findings li:last-child { border-bottom: 0; }
			.bs-finding-summary { font-weight: 500; color: var(--heading-color); }
			.bs-dim { opacity: 0.35; }
			.bs-short { color: var(--red-600, #cc2929); font-weight: 500; }
			.bs-line { cursor: pointer; }
			.bs-line:hover { background: var(--subtle-accent); }
			.bs-caret { display: inline-block; width: 14px; color: var(--text-muted);
				font-size: 10px; }
			.bs-why td { background: var(--subtle-accent); padding: 12px 13px 12px 27px; }
			.bs-why-why { color: var(--text-light); margin-bottom: 8px;
				font-size: var(--text-sm, 12px); }
			.bs-why-sum { font-family: var(--font-stack-mono, ui-monospace, monospace);
				font-size: var(--text-sm, 12px); color: var(--heading-color);
				margin-bottom: 10px; }
			.bs-why-tbl { width: 100%; border-collapse: collapse; font-size: var(--text-sm, 12px); }
			.bs-why-tbl th { text-align: left; font-weight: 500; color: var(--text-muted);
				padding: 4px 10px 4px 0; }
			.bs-why-tbl td { padding: 3px 10px 3px 0; color: var(--text-color); }
			.bs-stopped td { color: var(--text-muted); font-style: italic; }
			.bs-figure { padding: 14px 13px; overflow-x: auto; }
			.bs-figure svg { display: block; min-width: 620px; width: 100%; height: auto; }
		</style>`).appendTo(document.head);
	}
}

// ---- helpers ---------------------------------------------------------------

function describe_line(line) {
	if (line.estimated_from) return line.estimated_from;
	if (line.days) return __("{0} days", [line.days]);
	if (line.hours) return __("{0} hours", [line.hours]);
	if (line.quantity) return `${line.quantity} ${line.unit || ""}`.trim();
	return "";
}

// The drill: the same numbers the engine used, laid out so the arithmetic is
// checkable by eye. Nothing here recomputes anything — it renders what the line
// builder recorded while it was working the amount out.
function derivation_html(line, money) {
	const d = line.derivation;
	if (!d) return "";

	const rows = [];
	const add = (label, value) =>
		value !== undefined && value !== null && value !== "" &&
		rows.push(`<tr><th>${label}</th><td>${value}</td></tr>`);

	if (d.mode === "Daily" || d.mode === "Hourly") {
		add(__("Config ran"), `${d.segment_from} → ${d.segment_to}`);
		add(__("Locked rate"), money(d.locked_rate));
		if (d.mode === "Daily") {
			add(__("Days billed"), `${d.days} ${__("of")} ${d.day_units}`);
		} else {
			add(__("Hours on this date"), `${d.hours} ${__("of")} ${d.hour_units}`);
			add(__("Date"), d.charge_date);
		}
	} else if (d.mode === "Metered") {
		add(__("Measured"), `${d.measured_quantity} ${d.unit || ""}`.trim());
		add(__("Allowance"), `${d.allowance} ${d.unit || ""}`.trim());
		add(__("Billable"), `${d.billable_quantity} ${d.unit || ""}`.trim());
		add(__("Rate"), `${money(d.rate)} · ${d.rate_source}`);
	} else if (d.mode === "Estimated") {
		add(__("Window"), d.window_from ? `${d.window_from} → ${d.window_to}` : null);
		add(__("Months averaged"), d.months);
		add(__("Observed over the window"), d.observed_total ? money(d.observed_total) : null);
		add(__("Elapsed"), d.elapsed_days ? `${d.elapsed_days} ${__("of")} ${d.period_days}` : null);
	}

	// A date billed hourly is the confusing one, so name every config that shared it.
	let shared = "";
	if (d.configs_on_this_date && d.configs_on_this_date.length) {
		const items = d.configs_on_this_date
			.map(
				(c) =>
					`<tr><td>${c.from} → ${c.to}</td><td>${money(c.rate)}</td><td>${
						c.held_under_24h ? __("held under 24h") : ""
					}</td></tr>`
			)
			.join("");
		shared = `<table class="bs-why-tbl">
			<thead><tr><th>${__("Configs sharing this date")}</th><th>${__("Rate")}</th><th></th></tr></thead>
			<tbody>${items}</tbody></table>`;
	}

	return `
		<div class="bs-why-why">${frappe.utils.escape_html(d.why || "")}</div>
		<div class="bs-why-sum">${frappe.utils.escape_html(d.arithmetic || "")} = ${money(
			line.amount
		)}</div>
		<table class="bs-why-tbl">${rows.join("")}</table>
		${shared}`;
}

function basis_tag(line) {
	const estimated = line.basis && line.basis !== "Measured";
	const cls = estimated ? "bs-dot-estimated" : "bs-dot-measured";
	return `<span class="bs-basis"><span class="bs-dot ${cls}"></span>${frappe.utils.escape_html(
		line.basis || "Measured"
	)}</span>`;
}

// Both branches on one axis. The fork is the point: an operator asking what happens to
// this team wants settlement and escalation side by side, not one behind a toggle.
function timeline_svg(calendar, outcome) {
	// Dim the arm the data rules out, so the entailed branch reads at a glance without
	// the other one disappearing — an operator still needs to see what settling looks
	// like even when it is not going to happen.
	const entailed = outcome && outcome.entailed_branch;
	const paid_dim = entailed === "if_never_paid" ? ' class="bs-dim"' : "";
	const unpaid_dim = entailed === "if_paid_on_time" ? ' class="bs-dim"' : "";
	const unpaid = calendar.if_never_paid || [];
	const dates = [calendar.opens_on, calendar.due_on, ...unpaid.map((s) => s.date)];
	const first = new Date(dates[0]);
	const last = new Date(dates[dates.length - 1]);
	const span = Math.max(1, (last - first) / 86400000);

	const W = 860;
	const LEFT = 120;
	const RIGHT = 40;
	const x = (d) => LEFT + ((new Date(d) - first) / 86400000 / span) * (W - LEFT - RIGHT);

	const paid = calendar.if_paid_on_time[0];
	const fork = x(calendar.due_on);

	// Stages routinely share a date — the last retry and the overdue flip are the same
	// day by construction, since an invoice falls overdue once its retries are spent.
	// Drawing them as separate marks stacks two labels on one pixel.
	const by_date = new Map();
	for (const s of unpaid) {
		const label = s.attempt ? `${s.stage} ${s.attempt}` : s.stage;
		const group = by_date.get(s.date) || { date: s.date, labels: [], terminal: false };
		group.labels.push(label);
		group.terminal = group.terminal || s.stage === "Suspend" || s.stage === "Terminate";
		by_date.set(s.date, group);
	}

	// Neighbouring dates can still be a few pixels apart (day 1 and day 3 of a 44-day
	// ladder), so alternate the labels between two rows rather than let them collide.
	let previous_x = -Infinity;
	let row = 0;
	const marks = [...by_date.values()]
		.map((g) => {
			const px = x(g.date);
			row = px - previous_x < 70 ? 1 - row : 0;
			previous_x = px;
			const date_y = 102 - row * 14;
			const label_y = 148 + row * 14;
			const glyph = g.terminal
				? `<rect x="${px - 4}" y="107" width="8" height="26" fill="var(--red-500, #e03636)"></rect>`
				: `<circle cx="${px}" cy="120" r="4" fill="var(--red-500, #e03636)"></circle>`;
			return `${glyph}
				<text x="${px}" y="${date_y}" font-size="10" text-anchor="middle"
					fill="var(--text-color)">${frappe.datetime.str_to_user(g.date)}</text>
				<text x="${px}" y="${label_y}" font-size="10" text-anchor="middle"
					fill="var(--text-muted)">${g.labels.join(" · ")}</text>`;
		})
		.join("");

	return $(`
		<svg viewBox="0 0 ${W} 176" role="img"
			aria-label="${__("Both branches of what happens after the invoice falls due")}">
			<text x="4" y="30" font-size="11" font-weight="600"${paid_dim}
				fill="var(--green-600, #30a66d)">${__("If paid on time")}</text>
			<text x="4" y="124" font-size="11" font-weight="600"${unpaid_dim}
				fill="var(--red-600, #cc2929)">${__("If never paid")}</text>

			<line x1="${LEFT}" y1="72" x2="${W - RIGHT}" y2="72"
				stroke="var(--border-color)"></line>
			<line x1="${LEFT}" y1="72" x2="${fork}" y2="72"
				stroke="var(--text-light)" stroke-width="2"></line>
			<circle cx="${LEFT}" cy="72" r="4" fill="var(--text-light)"></circle>
			<text x="${LEFT}" y="58" font-size="10" text-anchor="middle"
				fill="var(--text-color)">${__("Opens")} ${frappe.datetime.str_to_user(
					calendar.opens_on
				)}</text>

			<circle cx="${fork}" cy="72" r="4.5" fill="var(--text-color)"></circle>
			<text x="${fork}" y="44" font-size="10.5" text-anchor="middle" font-weight="600"
				fill="var(--text-color)">${__("Due")} ${frappe.datetime.str_to_user(
					calendar.due_on
				)}</text>

			<g${paid_dim}>
			<path d="M ${fork} 72 C ${fork + 26} 72, ${fork + 26} 26, ${fork + 52} 26"
				fill="none" stroke="var(--green-500, #59ba8b)" stroke-width="2"></path>
			<circle cx="${fork + 52}" cy="26" r="4" fill="var(--green-500, #59ba8b)"></circle>
			<text x="${fork + 64}" y="30" font-size="10.5"
				fill="var(--green-600, #30a66d)">${__("Settled")} ${frappe.datetime.str_to_user(
					paid.date
				)}</text>
			</g>

			<g${unpaid_dim}>
			<path d="M ${fork} 72 C ${fork + 26} 72, ${fork + 26} 120, ${fork + 52} 120"
				fill="none" stroke="var(--red-500, #e03636)" stroke-width="2"></path>
			<line x1="${fork + 52}" y1="120" x2="${W - RIGHT}" y2="120"
				stroke="var(--red-500, #e03636)" stroke-width="2"></line>
			${marks}
			</g>
		</svg>`);
}
