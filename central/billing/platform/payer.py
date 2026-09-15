# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payer resolution for Paid-by-Partner billing (ADR 0007, v2-billing-specs).

Every module in `central.billing` assumes `team` is the payer — no
`resolve_payer()` seam existed before this. This is that seam: `resolve_billing_team`
answers "who pays for this team's usage on this date" for a single point in time
(credit wallet / payment method resolution, dunning); `payer_segments` and
`paid_by_partner_client_segments` split a whole billing period by day where the
answer changed, for `generate.py`'s per-team invoice rating. Nothing here writes;
all three are pure reads over `Partner Client Link`.

`Invoice.team` never changes because of any of this — I6 (one live invoice per
team per period) stays exactly as it was. Only which wallet is debited, which
payment method is charged, who is dunned, and which line items land on which
team's invoice are affected.
"""

import frappe

_LINKED_STATUSES = ("Approved", "Delinked")


def resolve_billing_team(team: str, on_date=None) -> str:
	"""The team that actually pays for `team`'s usage on `on_date` (default today).

	Returns `team` itself unless a paid-by-partner link's window covers that date.
	"""
	on_date = frappe.utils.getdate(on_date or frappe.utils.nowdate())
	link = _covering_link(team, on_date)
	return link.partner_team if link else team


def _covering_link(team: str, on_date):
	for row in _client_links(team, end_before=None):
		start = frappe.utils.getdate(row.approved_on)
		end = frappe.utils.getdate(row.delinked_on) if row.delinked_on else None
		if start <= on_date and (end is None or on_date <= end):
			return row
	return None


def _client_links(team: str, end_before=None) -> list:
	"""Every paid-by-partner link this client team has ever had (Approved or since
	Delinked) — `approved_on` is always set once a link reaches either status."""
	filters = {
		"client_team": team,
		"paid_by_partner": 1,
		"status": ["in", _LINKED_STATUSES],
	}
	if end_before is not None:
		filters["approved_on"] = ["<=", end_before]
	return frappe.get_all(
		"Partner Client Link",
		filters=filters,
		fields=["name", "partner_team", "approved_on", "delinked_on"],
	)


def payer_segments(team: str, period_start, period_end) -> list[dict]:
	"""Split [period_start, period_end] into contiguous day-range segments by payer.

	Each segment is `{"start": date, "end": date, "payer": team}`, exhaustive over
	the period. A team with no paid-by-partner history in the window gets back one
	segment covering the whole period, payer=itself; a mid-period approve/delink
	produces more than one.
	"""
	period_start = frappe.utils.getdate(period_start)
	period_end = frappe.utils.getdate(period_end)
	links = [
		link
		for link in _client_links(team, end_before=period_end)
		if not link.delinked_on or frappe.utils.getdate(link.delinked_on) >= period_start
	]
	if not links:
		return [{"start": period_start, "end": period_end, "payer": team}]

	cuts = {period_start, frappe.utils.add_days(period_end, 1)}
	for link in links:
		start = frappe.utils.getdate(link.approved_on)
		if period_start < start <= period_end:
			cuts.add(start)
		if link.delinked_on:
			resumes = frappe.utils.add_days(frappe.utils.getdate(link.delinked_on), 1)
			if period_start < resumes <= period_end:
				cuts.add(resumes)
	ordered_cuts = sorted(cuts)

	segments = []
	for start, next_start in zip(ordered_cuts, ordered_cuts[1:]):
		end = frappe.utils.add_days(next_start, -1)
		payer = team
		for link in links:
			link_start = frappe.utils.getdate(link.approved_on)
			link_end = frappe.utils.getdate(link.delinked_on) if link.delinked_on else None
			if link_start <= start and (link_end is None or end <= link_end):
				payer = link.partner_team
				break
		segments.append({"start": start, "end": end, "payer": payer})
	return _merge_adjacent(segments)


def _merge_adjacent(segments: list[dict]) -> list[dict]:
	"""Fold consecutive same-payer segments into one, so a cut from a link that
	doesn't actually change the payer at that boundary doesn't fragment the result."""
	merged = [dict(segments[0])]
	for seg in segments[1:]:
		if seg["payer"] == merged[-1]["payer"]:
			merged[-1]["end"] = seg["end"]
		else:
			merged.append(dict(seg))
	return merged


def paid_by_partner_client_segments(partner_team: str, period_start, period_end) -> list[dict]:
	"""Every client's partner-attributed day-range within the period, for consolidating
	onto the partner's own invoice: `{"client_team", "start", "end"}` per contiguous
	range. A client that was linked for only part of the period contributes only
	that part — the rest is theirs (see `payer_segments` for that side)."""
	period_start = frappe.utils.getdate(period_start)
	period_end = frappe.utils.getdate(period_end)
	links = frappe.get_all(
		"Partner Client Link",
		filters={
			"partner_team": partner_team,
			"paid_by_partner": 1,
			"status": ["in", _LINKED_STATUSES],
			"approved_on": ["<=", period_end],
		},
		fields=["client_team", "approved_on", "delinked_on"],
	)
	out = []
	for link in links:
		start = max(period_start, frappe.utils.getdate(link.approved_on))
		end = min(period_end, frappe.utils.getdate(link.delinked_on)) if link.delinked_on else period_end
		if start <= end:
			out.append({"client_team": link.client_team, "start": start, "end": end})
	return out
