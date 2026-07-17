# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Phase 1 (28th, off-peak): reconcile-if-stale, then draft.

Per team/subscription, compute day-weighted fixed lines (from Subscription
Change rate-snapshot segments) plus metered overage, apply the commitment
adjustment, and create a `Draft`. Idempotent per (team, period) — and idempotent
*under concurrency*, which is a different and stronger claim (ADR 0018).

The "does an invoice already exist?" read below is a fast path, not the guarantee.
The guarantee is the unique index on `Invoice.period_key`: two workers that both
read "no invoice" and both insert will see one succeed and the other take a
DuplicateEntryError, which `_insert_invoice` translates back into "the other worker
billed this period". Without it the read-then-insert is a time-of-check /
time-of-use gap, and `generate_draft_invoices` enqueues one job *per team* — so a
scheduler double-fire or a manual run overlapping the cron double-billed the team.
"""

import frappe

from central.billing.catalog import commitments
from central.billing.revenue.invoicing.lines import compute_line_items


def _live_invoice(team: str, billing_group: str | None, period_start, period_end) -> str | None:
	"""The team's existing live (non-cancelled) invoice for the period, if any."""
	return frappe.db.get_value(
		"Invoice",
		{
			"team": team,
			"billing_group": billing_group if billing_group else ["in", [None, ""]],
			"period_start": period_start,
			"period_end": period_end,
			"status": ["!=", "Cancelled"],
		},
		"name",
	)


def _resource_group_map(team: str) -> dict:
	"""asset_id -> billing_group for the team's *grouped* subscriptions.

	Only assets tagged into a Billing Group appear; anything absent is ungrouped
	and belongs to the team's consolidated invoice."""
	rows = frappe.get_all(
		"Subscription", filters={"team": team}, fields=["asset_id", "billing_group"]
	)
	return {r.asset_id: r.billing_group for r in rows if r.asset_id and r.billing_group}


def _scope_lines(lines: list[dict], team: str, billing_group: str | None) -> list[dict]:
	"""Keep only the lines belonging to this invoice's Billing-Group scope.

	Each line carries its resource (`subscription_resource`); a resource maps to a
	group via its subscription. `billing_group` unset = the consolidated scope
	(every ungrouped asset, plus standalone metered resources that map to no group)."""
	group_map = _resource_group_map(team)
	return [l for l in lines if group_map.get(l.get("subscription_resource")) == billing_group]


def _team_invoice_groups(team: str) -> list:
	"""The invoice scopes to draft for a team this period: the consolidated bucket
	(None) plus one per distinct Billing Group its subscriptions are tagged into."""
	groups = sorted({
		bg for bg in frappe.get_all("Subscription", filters={"team": team}, pluck="billing_group") if bg
	})
	return [None, *groups]
# Frappe surfaces a unique-key conflict two ways: UniqueValidationError from its own
# pre-insert check, and DuplicateEntryError when the write reaches the database first.
# Under real concurrency both occur, so both mean the same thing here.
_ALREADY_BILLED = (frappe.UniqueValidationError, frappe.DuplicateEntryError)


def _insert_invoice(payload: dict) -> str:
	"""Insert the draft, or yield to the worker that got there first.

	A unique-key conflict here is not an error — it is the index doing its job. Another
	worker billed this (team, period) between our check and our insert; its invoice is
	the invoice, and we return it rather than billing the team a second time.
	"""
	try:
		return frappe.get_doc(payload).insert(ignore_permissions=True).name
	except _ALREADY_BILLED:
		frappe.db.rollback()
		existing = _live_invoice(
			payload["team"], payload.get("billing_group"), payload["period_start"], payload["period_end"]
		)
		if not existing:
			raise  # a conflict on some other unique key — don't swallow it
		frappe.logger("billing").info(
			f"({payload['team']}, {payload['period_start']}) was billed concurrently as "
			f"{existing} — yielding to it"
		)
		return existing


def reconcile_subscription(subscription_doc):
	"""Refresh the current period's metered figures from the cluster manager if stale.

	Agentless (ADR 0006): Central wrote the event-log segments itself at provision
	time, so in the common case they're already local and this is a no-op. A real
	refresh would read live usage from the cluster manager; wired here as the seam,
	exercised by the reconciliation job.
	"""
	return False  # not stale — use what Central already recorded


def generate_draft_invoice(subscription: str, period_start, period_end):
	"""Reconcile-then-draft one subscription. Idempotent per (subscription, period).

	Returns the (existing or newly created) Draft invoice name, or None when the
	subscription had no billable runtime in the period.
	"""
	sub = frappe.get_doc("Subscription", subscription)
	reconcile_subscription(sub)

	# Keyed on the TEAM, not the subscription: a team gets one bill per period across
	# every subscription and cluster it runs (the same grain generate_team_invoice
	# bills at, and the grain the unique index enforces).
	existing = _live_invoice(sub.team, sub.billing_group, period_start, period_end)
	if existing:
		return existing

	from central.billing.revenue.metering import metered_line_items
	from central.billing.catalog.trials import invoice_type_for

	cluster = frappe.db.get_value("Asset", sub.asset_id, "cluster") if sub.asset_id else None
	lines = compute_line_items(sub.team, cluster, period_start, period_end)
	lines += metered_line_items(sub.team, cluster, period_start, period_end)
	# Draft only this subscription's own Billing-Group scope, even if other assets
	# share its cluster (they bill on their own group's / the consolidated invoice).
	lines = _scope_lines(lines, sub.team, sub.billing_group)
	if not lines:
		return None

	from central.billing.revenue.tax import resolve_tax

	subtotal = frappe.utils.flt(sum(line["amount"] for line in lines), 2)
	# Commitment (#30 discount / #31 clawback) adjusts the taxable base; subtotal
	# stays gross. Discount reduces it; a breach clawback adds the repaid discount.
	commitment = commitments.resolve_commitment(sub.team, lines, period_start)
	discount = commitment["discount"]
	clawback = commitment["clawback"]
	taxable_base = frappe.utils.flt(subtotal - discount + clawback, 2)
	currency = frappe.db.get_value("Billing Profile", sub.team, "currency")
	tax = resolve_tax(sub.team, taxable_base)
	total = frappe.utils.flt(taxable_base + tax["output_tax_amount"], 2)
	# expected_collection = total - tds (credits reduce it further at open).
	expected = frappe.utils.flt(total - tax["tds_amount"], 2)

	# The single branch point: an entry-tier (free/trial) team's invoice is a
	# cost_report — computed identically, but a true cost rather than a bill.
	name = _insert_invoice(
		{
			"doctype": "Invoice",
			"team": sub.team,
			"billing_group": sub.billing_group,
			"invoice_type": invoice_type_for(sub.team),
			"status": "Draft",
			"period_start": period_start,
			"period_end": period_end,
			"currency": currency,
			"items": lines,
			"subtotal": subtotal,
			"commitment_discount": discount,
			"commitment_clawback": clawback,
			"output_tax_type": tax["output_tax_type"],
			"output_tax_rate": tax["output_tax_rate"],
			"output_tax_amount": tax["output_tax_amount"],
			"zero_rating_reason": tax["zero_rating_reason"],
			"tds_applicable": tax["tds_applicable"],
			"tds_rate": tax["tds_rate"],
			"tds_amount": tax["tds_amount"],
			"total": total,
			"credit_applied": 0,
			"expected_collection": expected,
			"amount_paid": 0,
		}
	)
	commitments.mark_breached(commitment)
	return name


def generate_team_invoice(team: str, period_start, period_end, billing_group: str | None = None):
	"""One consolidated invoice per team per period, across every cluster it runs in.

	A team that runs instances in several regions should see a SINGLE monthly
	invoice, not one per region — so this aggregates the day-weighted fixed lines
	plus metered overage from all of the team's clusters into one Invoice.
	Idempotent per (team, period) — including under concurrency, which the read below
	cannot deliver on its own. `generate_draft_invoices` enqueues one job per team, so
	two workers could both read "no invoice" and both insert; the unique index on
	`period_key` is what stops the team being billed twice (ADR 0018).

	`billing_group` scopes the invoice: unset = the team's consolidated invoice; set
	= the separate invoice for that group's assets. The team is always the biller;
	the group only partitions how many invoices the team receives.
	"""
	existing = _live_invoice(team, billing_group, period_start, period_end)
	if existing:
		return existing

	from central.billing.revenue.metering import metered_line_items
	from central.billing.revenue.tax import resolve_tax
	from central.billing.catalog.trials import invoice_type_for

	asset_ids = frappe.get_all("Subscription", filters={"team": team}, pluck="asset_id")
	clusters = sorted({
		c for c in frappe.get_all("Asset", filters={"name": ["in", asset_ids]}, pluck="cluster") if c
	})
	lines = []
	for cluster in clusters:
		lines += compute_line_items(team, cluster, period_start, period_end)
		lines += metered_line_items(team, cluster, period_start, period_end)
	# Restrict to this invoice's scope: a specific Billing Group, or (unset) the
	# team's consolidated set of ungrouped assets.
	lines = _scope_lines(lines, team, billing_group)
	if not lines:
		return None

	subtotal = frappe.utils.flt(sum(line["amount"] for line in lines), 2)
	# Commitment (#30 discount / #31 clawback) adjusts the taxable base; subtotal
	# stays gross. Discount reduces it; a breach clawback adds the repaid discount.
	commitment = commitments.resolve_commitment(team, lines, period_start)
	discount = commitment["discount"]
	clawback = commitment["clawback"]
	taxable_base = frappe.utils.flt(subtotal - discount + clawback, 2)
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	tax = resolve_tax(team, taxable_base)
	total = frappe.utils.flt(taxable_base + tax["output_tax_amount"], 2)
	expected = frappe.utils.flt(total - tax["tds_amount"], 2)

	name = _insert_invoice(
		{
			"doctype": "Invoice",
			"team": team,
			"billing_group": billing_group,
			"invoice_type": invoice_type_for(team),
			"status": "Draft",
			"period_start": period_start,
			"period_end": period_end,
			"currency": currency,
			"items": lines,
			"subtotal": subtotal,
			"commitment_discount": discount,
			"commitment_clawback": clawback,
			"output_tax_type": tax["output_tax_type"],
			"output_tax_rate": tax["output_tax_rate"],
			"output_tax_amount": tax["output_tax_amount"],
			"zero_rating_reason": tax["zero_rating_reason"],
			"tds_applicable": tax["tds_applicable"],
			"tds_rate": tax["tds_rate"],
			"tds_amount": tax["tds_amount"],
			"total": total,
			"credit_applied": 0,
			"expected_collection": expected,
			"amount_paid": 0,
		}
	)
	commitments.mark_breached(commitment)
	return name


def generate_draft_invoices(period_start, period_end, enqueue: bool = False) -> list[str]:
	"""Phase-1 orchestrator: one consolidated draft per team, plus one per Billing Group.

	A team's ungrouped assets bill on a single consolidated invoice (aggregating all
	its clusters); each Billing Group its assets are tagged into bills on its own
	separate invoice for the same period. A team with no groups gets just the one
	consolidated invoice — today's behaviour. All invoices bill to the team.
	"""
	teams = sorted({s.team for s in frappe.get_all("Subscription", fields=["team"]) if s.team})
	created = []
	for team in teams:
		for billing_group in _team_invoice_groups(team):
			if enqueue:
				frappe.enqueue(
					"central.billing.revenue.invoicing.generate_team_invoice",
					team=team,
					period_start=period_start,
					period_end=period_end,
					billing_group=billing_group,
				)
				continue
			name = generate_team_invoice(team, period_start, period_end, billing_group=billing_group)
			if name:
				created.append(name)
	return created
