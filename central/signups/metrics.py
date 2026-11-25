from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import TYPE_CHECKING

import frappe
from frappe.query_builder.functions import Min
from frappe.utils import get_datetime

from central.integrations.metrics import FAILURES_NAMED

if TYPE_CHECKING:
	from central.integrations.metrics import CentralMetrics

FAILED_ACTION_STATUSES = ("Failed", "Timed Out")


def add_signup_metrics(metrics: CentralMetrics) -> None:
	"""The signup funnel of the last hour by product, the time from a trial request to a ready site,
	and the trial that waits longest for its site. A trial is a Site create action."""
	hour_ago = metrics.now - timedelta(hours=1)
	verified = frappe.db.count("User", {"creation": (">", hour_ago)})
	metrics.add("central_signup_steps_last_hour", verified, step="verified", product="none")

	requested = frappe.get_all(
		"Resource Action",
		filters={"resource_type": "Site", "action": "create", "creation": (">", hour_ago)},
		pluck="product",
	)
	failed = frappe.get_all(
		"Resource Action",
		filters={
			"resource_type": "Site",
			"action": "create",
			"status": ("in", FAILED_ACTION_STATUSES),
			"completed_at": (">", hour_ago),
		},
		fields=["product", "title", "subdomain", "error_code", "status"],
		order_by="completed_at desc",
	)
	ready = get_ready_signups(hour_ago)
	for step, products in (
		("requested", requested),
		("ready", [row.product for row in ready]),
		("failed", [row.product for row in failed]),
	):
		for product, count in Counter(product or "none" for product in products).items():
			metrics.add("central_signup_steps_last_hour", count, step=step, product=product)

	for row in failed[:FAILURES_NAMED]:
		site = row.title or row.subdomain or "none"
		metrics.add(
			"central_signup_failed",
			1,
			product=row.product or "none",
			site=site,
			error=row.error_code or row.status,
		)

	add_signup_setup_times(metrics, ready)
	for row in get_waiting_signups(metrics.now - timedelta(days=1)):
		age = metrics.get_age(row.oldest)
		metrics.add("central_signup_oldest_waiting_seconds", age, region=row.region or "none")


def add_signup_setup_times(metrics: CentralMetrics, ready: list[frappe._dict]) -> None:
	"""The median and the longest time from request to ready site, for each region."""
	seconds: dict[str, list[float]] = {}
	for row in ready:
		wait = (get_datetime(row.ready_at) - get_datetime(row.requested_at)).total_seconds()
		seconds.setdefault(row.region or "none", []).append(max(wait, 0))
	for region, waits in seconds.items():
		metrics.add("central_signup_setup_seconds", median(waits), region=region, quantile="p50")
		metrics.add("central_signup_setup_seconds", max(waits), region=region, quantile="max")


def get_ready_signups(since: datetime) -> list[frappe._dict]:
	"""Trial sites that became ready since the given time, with the time of their request."""
	action = frappe.qb.DocType("Resource Action")
	site = frappe.qb.DocType("Site")
	return (
		frappe.qb.from_(action)
		.join(site)
		.on(site.server == action.server)
		.select(action.region, action.product, action.creation.as_("requested_at"), site.ready_at)
		.where((action.resource_type == "Site") & (action.action == "create") & (site.ready_at > since))
		.run(as_dict=True)
	)


def get_waiting_signups(since: datetime) -> list[frappe._dict]:
	"""For each region, the oldest trial request since the given time that has no ready site, did not
	fail, and whose server is not terminated. A terminated trial server never gets a site."""
	action = frappe.qb.DocType("Resource Action")
	site = frappe.qb.DocType("Site")
	server = frappe.qb.DocType("Virtual Machine")
	return (
		frappe.qb.from_(action)
		.left_join(site)
		.on(site.server == action.server)
		.left_join(server)
		.on(server.name == action.server)
		.select(action.region, Min(action.creation).as_("oldest"))
		.where(
			(action.resource_type == "Site")
			& (action.action == "create")
			& (action.creation > since)
			& action.status.notin(FAILED_ACTION_STATUSES)
			& site.ready_at.isnull()
			& (server.status.isnull() | (server.status != "Terminated"))
		)
		.groupby(action.region)
		.run(as_dict=True)
	)


def add_card_setup_metrics(metrics: CentralMetrics) -> None:
	"""Card and UPI setups of the last hour by outcome, the failed ones by name, teams that started
	setups and finished none, and the oldest setup that is still open."""
	hour_ago = metrics.now - timedelta(hours=1)
	setups = frappe.get_all(
		"Payment Method",
		or_filters={"creation": (">", hour_ago), "modified": (">", hour_ago)},
		fields=[
			"team",
			"gateway",
			"method_type",
			"status",
			"creation",
			"validated_at",
			"failure_code",
			"decline_code",
		],
		order_by="modified desc",
	)
	outcomes = Counter()
	for row in setups:
		for outcome in get_card_setup_outcomes(row, hour_ago):
			outcomes[(row.gateway or "none", row.method_type or "none", outcome)] += 1
	for (gateway, method_type, outcome), count in outcomes.items():
		metrics.add(
			"central_card_setups_last_hour", count, gateway=gateway, method_type=method_type, outcome=outcome
		)

	failed = [row for row in setups if "failed" in get_card_setup_outcomes(row, hour_ago)]
	for row in failed[:FAILURES_NAMED]:
		code = row.decline_code or row.failure_code or "none"
		metrics.add("central_card_setup_failed", 1, gateway=row.gateway or "none", team=row.team, code=code)

	add_unfinished_card_setups(metrics, setups, hour_ago)
	oldest: dict[str, datetime] = {}
	for row in frappe.get_all(
		"Payment Method", filters={"status": "Pending Validation"}, fields=["gateway", "creation"]
	):
		gateway = row.gateway or "none"
		oldest[gateway] = min(oldest.get(gateway, row.creation), row.creation)
	for gateway, creation in oldest.items():
		metrics.add("central_card_setup_oldest_pending_seconds", metrics.get_age(creation), gateway=gateway)


def get_card_setup_outcomes(row: frappe._dict, since: datetime) -> list[str]:
	"""What happened to one setup since the given time. A Cancelled setup is one that the team's next
	attempt replaced, so it is not an outcome. A card that was checked once and fails later is not a setup."""
	outcomes = []
	if get_datetime(row.creation) > since:
		outcomes.append("started")
	if row.validated_at:
		if get_datetime(row.validated_at) > since:
			outcomes.append("succeeded")
	elif row.status in ("Failed", "Expired"):
		outcomes.append(row.status.lower())
	return outcomes


def add_unfinished_card_setups(metrics: CentralMetrics, setups: list[frappe._dict], since: datetime) -> None:
	"""Teams that started 2 or more setups in the last hour and finished none. The customer keeps
	trying and the card does not save."""
	started = Counter(row.team for row in setups if get_datetime(row.creation) > since)
	finished = {row.team for row in setups if "succeeded" in get_card_setup_outcomes(row, since)}
	for team, attempts in started.items():
		if attempts >= 2 and team not in finished:
			metrics.add("central_card_setup_unfinished_attempts", attempts, team=team)


def add_conversion_metrics(metrics: CentralMetrics) -> None:
	"""Active trials whose team has had an active card for 10 min, by the reason the trial records, and
	converted trials whose server still runs a trial plan. A card converts an active trial at once."""
	from central.signups.trial import get_unmoved_conversions

	site = frappe.qb.DocType("Site")
	method = frappe.qb.DocType("Payment Method")
	blocked = (
		frappe.qb.from_(site)
		.join(method)
		.on(method.team == site.team)
		.select(site.name, site.trial_error)
		.distinct()
		.where(
			(site.trial_state == "Active")
			& (method.status == "Active")
			& (method.validated_at < metrics.now - timedelta(minutes=10))
		)
		.run(as_dict=True)
	)
	for reason, count in Counter((row.trial_error or "none")[:120] for row in blocked).items():
		metrics.add("central_trial_conversions_blocked", count, reason=reason)
	metrics.add("central_trial_conversions_unmoved", len(get_unmoved_conversions()))
