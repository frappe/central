# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Phase 1 (28th, off-peak): reconcile-if-stale, then draft.

Per team/subscription, compute day-weighted fixed lines (from the Central
price-lock segments) plus metered overage, apply the commitment adjustment, and
create a `Draft`. Idempotent per (team/subscription, period).
"""

import frappe

from central.billing.catalog import commitments
from central.billing.revenue.invoicing.lines import compute_line_items


def reconcile_subscription(subscription_doc):
	"""Pull from the Agent only if the local data is stale.

	Sync is push-primary (#03), so in the common case the event-log segments are
	already on Central and this is a no-op. A real pull would call the Agent's
	get_team_usage; wired here as the seam, exercised by the reconciliation job.
	"""
	return False  # not stale — use what was pushed


def generate_draft_invoice(subscription: str, period_start, period_end):
	"""Reconcile-then-draft one subscription. Idempotent per (subscription, period).

	Returns the (existing or newly created) Draft invoice name, or None when the
	subscription had no billable runtime in the period.
	"""
	sub = frappe.get_doc("Subscription", subscription)
	reconcile_subscription(sub)

	existing = frappe.db.get_value(
		"Invoice",
		{
			"subscription": subscription,
			"period_start": period_start,
			"period_end": period_end,
			"status": ["!=", "Cancelled"],
		},
		"name",
	)
	if existing:
		return existing

	from central.billing.revenue.metering import metered_line_items
	from central.billing.catalog.trials import invoice_type_for

	lines = compute_line_items(sub.team, sub.cluster, period_start, period_end)
	lines += metered_line_items(sub.team, sub.cluster, period_start, period_end)
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
	currency = frappe.db.get_value(
		"Price Lock", {"team": sub.team, "cluster": sub.cluster}, "currency"
	)
	tax = resolve_tax(sub.team, taxable_base)
	total = frappe.utils.flt(taxable_base + tax["output_tax_amount"], 2)
	# expected_collection = total - tds (credits reduce it further at open).
	expected = frappe.utils.flt(total - tax["tds_amount"], 2)

	# The single branch point: an entry-tier (free/trial) team's invoice is a
	# cost_report — computed identically, but a true cost rather than a bill.
	invoice = frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": sub.team,
			"subscription": subscription,
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
	).insert(ignore_permissions=True)
	commitments.mark_breached(commitment)
	return invoice.name


def generate_team_invoice(team: str, period_start, period_end, subscription: str | None = None):
	"""One consolidated invoice per team per period, across every cluster it runs in.

	A team that runs instances in several regions should see a SINGLE monthly
	invoice, not one per region — so this aggregates the day-weighted fixed lines
	plus metered overage from all of the team's clusters into one Invoice.
	Idempotent per (team, period): a second call returns the existing invoice.

	`subscription` is the primary subscription (its default payment method funds
	the auto-charge in open_and_collect); defaults to any of the team's subs.
	"""
	existing = frappe.db.get_value(
		"Invoice",
		{
			"team": team,
			"period_start": period_start,
			"period_end": period_end,
			"status": ["!=", "Cancelled"],
		},
		"name",
	)
	if existing:
		return existing

	from central.billing.revenue.metering import metered_line_items
	from central.billing.revenue.tax import resolve_tax
	from central.billing.catalog.trials import invoice_type_for

	clusters = sorted(c for c in set(frappe.get_all("Price Lock", {"team": team}, pluck="cluster")) if c)
	lines = []
	for cluster in clusters:
		lines += compute_line_items(team, cluster, period_start, period_end)
		lines += metered_line_items(team, cluster, period_start, period_end)
	if not lines:
		return None

	subtotal = frappe.utils.flt(sum(line["amount"] for line in lines), 2)
	# Commitment (#30 discount / #31 clawback) adjusts the taxable base; subtotal
	# stays gross. Discount reduces it; a breach clawback adds the repaid discount.
	commitment = commitments.resolve_commitment(team, lines, period_start)
	discount = commitment["discount"]
	clawback = commitment["clawback"]
	taxable_base = frappe.utils.flt(subtotal - discount + clawback, 2)
	currency = frappe.db.get_value("Price Lock", {"team": team}, "currency")
	tax = resolve_tax(team, taxable_base)
	total = frappe.utils.flt(taxable_base + tax["output_tax_amount"], 2)
	expected = frappe.utils.flt(total - tax["tds_amount"], 2)
	if subscription is None:
		subscription = frappe.db.get_value("Subscription", {"team": team}, "name")

	invoice = frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": team,
			"subscription": subscription,
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
	).insert(ignore_permissions=True)
	commitments.mark_breached(commitment)
	return invoice.name


def generate_draft_invoices(period_start, period_end, enqueue: bool = False) -> list[str]:
	"""Phase-1 orchestrator: ONE consolidated draft per team for the period.

	A team that runs instances across several clusters still gets a single
	invoice (generate_team_invoice aggregates all its clusters). The team's first
	subscription is the primary (its payment method funds the auto-charge).
	"""
	primary = {}
	for s in frappe.get_all("Subscription", fields=["name", "team"], order_by="creation asc"):
		primary.setdefault(s.team, s.name)
	created = []
	for team, sub in primary.items():
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.generate_team_invoice",
				team=team,
				period_start=period_start,
				period_end=period_end,
				subscription=sub,
			)
			continue
		name = generate_team_invoice(team, period_start, period_end, subscription=sub)
		if name:
			created.append(name)
	return created
