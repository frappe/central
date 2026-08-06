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
		this.mode = this.page.add_field({
			fieldname: "mode",
			label: __("Outcomes"),
			fieldtype: "Select",
			options: ["Derived", "Optimistic", "Assumed"],
			default: "Derived",
			change: () => this.refresh(),
		});
		this.page.set_primary_action(__("Project"), () => this.refresh());
	}

	refresh() {
		const team = this.team.get_value();
		if (!team) return;

		const start = this.period.get_value() || frappe.datetime.month_start();
		this.show_empty(__("Projecting…"));
		frappe
			.call({
				method: "central.billing.api.admin.projection.project_team",
				args: { team, period_start: start, mode: this.mode.get_value() || "Derived" },
			})
			.then((r) => r.message && this.render(r.message))
			.catch(() => this.show_empty(__("Could not project this team.")));
	}

	show_empty(message) {
		this.$body.html(`<div class="bs-empty">${frappe.utils.escape_html(message)}</div>`);
	}

	render(data) {
		this.$body.empty();
		this.$body.append(this.invoice_card(data));
		if (data.outcome) this.$body.append(this.findings_card(data.outcome));
		this.$body.append(this.calendar_card(data.calendar, data.outcome));
		if (data.in_flight && data.in_flight.length) {
			this.$body.append(this.in_flight_card(data.in_flight, data.as_of));
		}
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
				(line) => `
			<tr>
				<td>${frappe.utils.escape_html(line.plan || line.resource_type || "—")}</td>
				<td class="bs-muted">${frappe.utils.escape_html(describe_line(line))}</td>
				<td class="bs-right">${money(line.amount)}</td>
				<td>${basis_tag(line)}</td>
			</tr>`
			)
			.join("");

		// A total is never shown on its own when part of it was inferred — a bill that
		// is half guesswork must not read like a bill.
		const split = invoice.has_estimates
			? `<div class="bs-total"><span>${__("Measured")}</span><span>${money(
					invoice.measured
			  )}</span></div>
			   <div class="bs-total"><span>${__("Estimated")}</span><span>${money(
					invoice.estimated
			  )}</span></div>`
			: "";

		const tax = invoice.output_tax_amount
			? `<div class="bs-total"><span>${frappe.utils.escape_html(
					invoice.output_tax_type
			  )} @ ${invoice.output_tax_rate}%</span><span>${money(
					invoice.output_tax_amount
			  )}</span></div>`
			: "";

		return $(`
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
