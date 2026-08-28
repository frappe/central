# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Phase 1 (heavy): reconcile-if-stale, then draft — one team at a time.

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

import time

import frappe

from central.billing.catalog import commitments
from central.billing.revenue.invoicing.lines import compute_line_items, team_line_items


def _live_invoice(team: str, period_start, period_end, for_update: bool = False) -> str | None:
	"""The team's existing live (non-cancelled) invoice for this period, if any.

	`for_update` is how the loser of an insert race finds the winner: a locking read
	sees the latest committed row, while a plain one is answered from the snapshot
	this transaction started with — which predates the winner's commit.
	"""
	return frappe.db.get_value(
		"Invoice",
		{
			"team": team,
			"period_start": period_start,
			"period_end": period_end,
			"status": ["!=", "Cancelled"],
		},
		"name",
		for_update=for_update,
	)


def _resource_project_map(team: str) -> dict:
	"""asset_id/service_subject -> (project, project_title) for the team's resources
	tagged into an *enabled* Project.

	Only resources tagged into one of the team's enabled Projects appear; anything
	absent — never tagged, or tagged into a disabled or another team's project — is
	untagged on the invoice. Purely a labelling concern now: every line still bills on
	the team's one consolidated invoice, whatever it maps to here.
	"""
	projects = frappe.get_all(
		"Project", filters={"team": team, "enabled": 1}, fields=["name", "title"]
	)
	titles = {p.name: p.title for p in projects}
	rows = frappe.get_all(
		"Subscription",
		filters={"team": team},
		fields=["asset_id", "service_subject", "project"],
	)
	out = {}
	for r in rows:
		if not r.project or r.project not in titles:
			continue
		resource_id = r.asset_id or r.service_subject
		if resource_id:
			out[resource_id] = (r.project, titles[r.project])
	return out


def _tag_projects(lines: list[dict], team: str) -> None:
	"""Stamp each billable line with the Project its resource is tagged into, if any.

	Mutates `lines` in place — a stored fact at generation time (real invoice) or at
	read time (a live forecast), never a live Link a caller has to re-resolve. Called
	from the one place every line passes through (`_rate`), so a real Invoice Line
	Item and a projected one are tagged identically.
	"""
	resource_project = _resource_project_map(team)
	if not resource_project:
		return
	for line in lines:
		tag = resource_project.get(line.get("subscription_resource"))
		if tag:
			line["project"], line["project_title"] = tag


# Frappe surfaces a unique-key conflict two ways: UniqueValidationError from its own
# pre-insert check, and DuplicateEntryError when the write reaches the database first.
# Under real concurrency both occur, so both mean the same thing here.
_ALREADY_BILLED = (frappe.UniqueValidationError, frappe.DuplicateEntryError)

_INSERT_SAVEPOINT = "invoice_insert"


def _insert_invoice(payload: dict) -> str:
	"""Insert the draft, or yield to the worker that got there first.

	A unique-key conflict here is not an error — it is the index doing its job. Another
	worker billed this (team, period) between our check and our insert; its invoice is
	the invoice, and we return it rather than billing the team a second time.

	Clearing the failed insert is a rollback to a savepoint, not a blanket one: the
	inline run bills many teams in a single transaction, and losing a race on this
	team must not discard the teams already drafted. The transaction therefore
	survives — so the read that finds the winner has to lock, or it would be
	answered from a snapshot taken before the winner committed.
	"""
	frappe.db.savepoint(_INSERT_SAVEPOINT)
	try:
		return frappe.get_doc(payload).insert(ignore_permissions=True).name
	except _ALREADY_BILLED:
		frappe.db.rollback(save_point=_INSERT_SAVEPOINT)
		existing = _live_invoice(
			payload["team"],
			payload["period_start"],
			payload["period_end"],
			for_update=True,
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

	# Keyed on the TEAM, not the subscription: a team gets one consolidated bill per
	# period across every subscription and cluster it runs (the same grain
	# generate_team_invoice bills at, and the grain the unique index enforces).
	existing = _live_invoice(sub.team, period_start, period_end)
	if existing:
		return existing

	rated = rate_subscription_period(subscription, period_start, period_end)
	if not rated:
		return None

	name = _insert_invoice(rated.payload)
	commitments.mark_breached(rated.commitment)
	return name


def _rate(team: str, lines: list[dict], period_start, period_end):
	"""Price a set of billable lines into an invoice payload. Reads only.

	The arithmetic every draft shares: gross subtotal, the commitment adjustment,
	tax on the adjusted base, and what we expect to actually collect. Nothing here
	writes, so the same call answers "what will this period cost?" for a period that
	has not happened yet.

	Every line passes through here on its way onto an invoice — real or projected —
	so this is also the one place a line is tagged with the Project its resource
	belongs to (`_tag_projects`), keeping a real Invoice Line Item and a forecast
	line tagged identically.

	Returns the payload alongside the commitment verdict that shaped it. The verdict
	is handed back rather than acted on because marking a commitment breached is a
	write, and this function does not do those.
	"""
	from central.billing.catalog.trials import invoice_type_for
	from central.billing.revenue.tax import resolve_tax

	_tag_projects(lines, team)
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
	# expected_collection = total - tds (credits reduce it further at open).
	expected = frappe.utils.flt(total - tax["tds_amount"], 2)

	return frappe._dict(
		commitment=commitment,
		# The single branch point: an entry-tier (free/trial) team's invoice is a
		# cost_report — computed identically, but a true cost rather than a bill.
		payload={
			"doctype": "Invoice",
			"team": team,
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
		},
	)


def rate_subscription_period(subscription: str, period_start, period_end, explain: bool = False):
	"""What one subscription's cluster would bill the team for the period. Reads only.

	Returns None when there was no billable runtime.
	"""
	from central.billing.revenue.metering import metered_line_items

	sub = frappe.get_doc("Subscription", subscription)
	cluster = frappe.db.get_value("Asset", sub.asset_id, "cluster") if sub.asset_id else None
	lines = compute_line_items(sub.team, cluster, period_start, period_end, explain=explain)
	lines += metered_line_items(sub.team, cluster, period_start, period_end, explain=explain)
	if not lines:
		return None
	return _rate(sub.team, lines, period_start, period_end)


def team_clusters(team: str) -> list[str]:
	"""Every cluster the team runs an asset in, resolved in one pass."""
	asset_ids = frappe.get_all("Subscription", filters={"team": team}, pluck="asset_id")
	return sorted(
		{c for c in frappe.get_all("Asset", filters={"name": ["in", asset_ids]}, pluck="cluster") if c}
	)


def rate_team_period(
	team: str,
	period_start,
	period_end,
	metered: list[dict] | None = None,
	explain: bool = False,
	changes=None,
):
	"""What the team would bill for the period, across every cluster. Reads only.

	The rating half of `generate_team_invoice` — same lines, same commitment, same
	tax, no insert. Returns None when the team has nothing billable.

	`metered` replaces the metered lines rather than adding to them. The run leaves it
	unset and bills the rollups that landed; a projection supplies estimated usage,
	because a period that has not happened has no rollups and would otherwise be rated
	as though the team used nothing.
	"""
	from central.billing.revenue.metering import metered_line_items_for_clusters

	# Read the team once, not once per cluster: team_line_items pulls every
	# subscription's fixed lines in one pass, and the metered rollups for all the
	# team's clusters come back in a single query.
	lines = team_line_items(team, period_start, period_end, explain=explain, changes=changes)
	if metered is None:
		lines += metered_line_items_for_clusters(
			team, team_clusters(team), period_start, period_end, explain=explain
		)
	else:
		lines += list(metered)
	if not lines:
		return None
	return _rate(team, lines, period_start, period_end)


def _generate_team_invoice(team: str, period_start, period_end):
	"""One consolidated invoice per team per period, across every cluster it runs in.

	A team that runs instances in several regions should see a SINGLE invoice, not
	one per region — so this aggregates the day-weighted fixed lines plus metered
	overage from all of the team's clusters into one Invoice. Idempotent per (team,
	period) — including under concurrency, which the read below cannot deliver on
	its own. `generate_draft_invoices` enqueues one job per team, so two workers
	could both read "no invoice" and both insert; the unique index on `period_key`
	is what stops the team being billed twice for the same period (ADR 0018).
	"""
	existing = _live_invoice(team, period_start, period_end)
	if existing:
		return existing

	rated = rate_team_period(team, period_start, period_end)
	if not rated:
		return None

	name = _insert_invoice(rated.payload)
	commitments.mark_breached(rated.commitment)
	return name


_INVOICE_DEADLOCK_RETRIES = 5


def generate_team_invoice(team: str, period_start, period_end):
	"""Generate one team's invoice, yielding cleanly when concurrent workers contend.

	The unique period key still decides the winner. A database deadlock is merely the
	lock manager picking a loser before that key can report the winner, so retry it and
	return the already-created invoice just like a duplicate-key race.
	"""
	for attempt in range(_INVOICE_DEADLOCK_RETRIES):
		try:
			return _generate_team_invoice(team, period_start, period_end)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == _INVOICE_DEADLOCK_RETRIES - 1:
				existing = _live_invoice(team, period_start, period_end, for_update=True)
				if existing:
					return existing
				raise
			time.sleep(0.05 * (attempt + 1))
