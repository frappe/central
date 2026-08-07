# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a price change actually reaches.

This is the misconception the simulator exists to dispel. Ask anyone outside the team
what raising VM prices 20% does to next month's revenue and they will multiply the book
by 1.2. They will be wrong by roughly everything, because a bundle's rate is snapshotted
as `locked_rate` on the Subscription Change row that opened its segment
([ADR 0010](../../docs/adr/0010-price-lock-folded-into-subscription-change.md)). Billing
reads that snapshot forever. Changing a Catalog Rate reaches new provisions and resizes
— nothing else.

So a projected line falls into one of two buckets, and the split is the answer:

  **Grandfathered** — billed from a rate locked when the resource was provisioned. A
  catalog change does not touch it, this month or any month, until the customer resizes.

  **Repriced** — billed from whatever the catalog says today. Live-priced families
  (depreciating storage, the deliberate exception to grandfathering) and any segment
  opened after the change land here.

A simulator that modelled a price rise as multiplication would encode the exact error it
was built to correct, so the classification is read from the derivation each line already
carries rather than guessed at.
"""

import frappe

GRANDFATHERED = "Grandfathered"
REPRICED = "Repriced"

# `metering` records where a metered line's rate came from; this is the phrase it uses
# for a family that reads the current catalog rather than terms locked at ingest.
_LIVE_RATE_SOURCE = "current catalog rate"


def classify(line: dict, effective_from=None) -> str:
	"""Which bucket one projected line belongs to.

	`effective_from` is the date a price change would take effect. A segment that opened
	on or after it was priced under the new catalog; everything older carries a snapshot
	taken before the change existed.
	"""
	derivation = line.get("derivation") or {}
	# An estimated line wraps the measured one it was inferred from. Estimating a
	# quantity says nothing about where the rate came from, so look through.
	measured = derivation.get("measured_basis") or {}

	if _LIVE_RATE_SOURCE in (derivation.get("rate_source"), measured.get("rate_source")):
		return REPRICED

	# `rate_locked_at`, never `segment_from`. The latter is clamped to the billing window,
	# so a resource provisioned in March reads as opening on the 1st of whatever month is
	# being projected — which would classify every long-running subscription as newly
	# priced and report the exact opposite of the truth.
	locked_at = derivation.get("rate_locked_at") or measured.get("rate_locked_at")
	if effective_from and locked_at:
		if frappe.utils.getdate(locked_at) >= frappe.utils.getdate(effective_from):
			return REPRICED

	return GRANDFATHERED


def split(lines: list, currency: str, effective_from=None) -> dict:
	"""Divide a projected invoice into what a price change reaches and what it does not."""
	buckets = {GRANDFATHERED: 0.0, REPRICED: 0.0}
	resources = {GRANDFATHERED: set(), REPRICED: set()}

	for line in lines or []:
		bucket = classify(line, effective_from)
		buckets[bucket] += frappe.utils.flt(line.get("amount"))
		if line.get("subscription_resource"):
			resources[bucket].add(line["subscription_resource"])

	return {
		"currency": currency,
		# Structural: how this bill is priced, regardless of which change is being asked
		# about. What a *particular* change did is the delta between the two projections —
		# a different question, and conflating them would over-claim whenever an override
		# touches one family and the bill contains another that merely happens to be
		# live-priced.
		"grandfathered": frappe.utils.flt(buckets[GRANDFATHERED], 2),
		"repriced": frappe.utils.flt(buckets[REPRICED], 2),
		"grandfathered_resources": len(resources[GRANDFATHERED]),
		"repriced_resources": len(resources[REPRICED]),
		"effective_from": str(effective_from) if effective_from else None,
	}


def with_delta(split_result: dict, live_total: float, altered_total: float) -> dict:
	"""Attach what the change actually did to how the bill is priced."""
	return {
		**split_result,
		"delta": frappe.utils.flt(altered_total - live_total, 2),
		"live_total": frappe.utils.flt(live_total, 2),
		"altered_total": frappe.utils.flt(altered_total, 2),
	}


def explain(live_total: float, altered_total: float, split_result: dict) -> str:
	"""One sentence an operator can act on, in place of a number they will misread."""
	delta = frappe.utils.flt(altered_total - live_total, 2)
	currency = split_result["currency"]
	grandfathered = split_result["grandfathered"]
	repriced = split_result["repriced"]

	if not delta:
		return (
			f"No change this period. {currency} {grandfathered:,.2f} is billed at rates locked "
			f"when each resource was provisioned, and a catalog change does not reach a locked "
			f"rate — only new provisions and resizes are priced from the new one."
		)

	return (
		f"{currency} {delta:,.2f} this period, from the {currency} {repriced:,.2f} that is "
		f"priced live. The other {currency} {grandfathered:,.2f} is grandfathered and moves "
		f"only when those resources are resized or replaced."
	)
