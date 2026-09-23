# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Priced whole-CPU server plans within the Team's policy and spending limit."""

import frappe
from frappe import _

from central.billing import authz
from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.catalog.composition import (
	COMPUTE,
	DISK,
	MEMORY,
	composition_quantities,
)
from central.billing.catalog.entitlements import get_team_caps


@frappe.whitelist()
def get_eligible_plans(
	cluster: str | None = None,
	team: str | None = None,
	exclude_subscription: str | None = None,
	for_resize: int | str | None = None,
) -> dict:
	"""Return the server catalog available to the authorized Team."""
	from central.billing.catalog.server_plans import get_server_plans

	return get_server_plans(
		_resolve_team(team),
		cluster=cluster,
		exclude_subscription=exclude_subscription,
		for_resize=for_resize,
	)


@frappe.whitelist(methods=["POST"])
def provision_composed_config(
	includes: list | str, sub_category: str, cluster: str, team: str | None = None
) -> dict:
	"""Provision a design-your-own config from the slider (#84). The server is the
	gate: it re-validates composition, ratio, steps, bounds (#81) and that the config
	fits current headroom (#83) before anything is created — a request that slips past
	the client is still refused here."""
	team = _resolve_team(team, require=authz.MANAGE)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	from central.billing.catalog.subscriptions import provision_composed_subscription

	return provision_composed_subscription(team, cluster, includes, sub_category)


def _lock_disclosure(team: str, subscription: str, currency: str) -> dict | None:
	"""What this server's rate is, against what the same shape costs today.

	A resize re-prices at current rates (ADR 0010), so a customer holding a rate
	below today's list is about to give it up — including if they resize back to the
	size they are on now. They are entitled to know that before they confirm, not
	after it shows up on a bill.

	Scoped to `team` even though the caller already resolved the subscription from
	a team-scoped read. A rate is tenant data, and a helper that takes a bare
	subscription id and trusts whoever passed it is one stray decorator away from
	handing another tenant's price to anyone who can guess an id — which is how
	this function was first shipped.
	"""
	from central.billing.api.dashboard.spend import list_rate_for
	from central.billing.catalog.subscriptions import active_segments

	segments = active_segments({"name": subscription, "team": team})
	if not segments:
		return None
	segment = segments[0]
	locked = frappe.utils.flt(segment.locked_rate)
	listed = list_rate_for(segment, currency)
	if listed is None or not locked:
		return None
	return {
		"locked_rate": locked,
		"list_rate": frappe.utils.flt(listed),
		"currency": currency,
		# Only a rate BELOW today's list is worth warning about; at or above it there
		# is nothing to lose by re-pricing.
		"gives_up": frappe.utils.flt(listed - locked, 2) if listed > locked else 0.0,
	}


@frappe.whitelist()
def get_composed_config(server: str, team: str | None = None) -> dict:
	"""The config running on `server`, pre-filling the resize slider (#84): its
	subscription, current shape, and the resize headroom — the cap minus the team's
	*other* run-rate, so the running config's own spend is available to it.

	Works for both a composed server (its exact composition + optimisation profile)
	and a preset one, whose shape is read off the mirrored VM; resizing a preset
	slides it onto a custom config, so `sub_category` is None and the slider defaults
	to the region's first profile. `{resizable: False}` when there's no live
	subscription to resize."""
	team = _resolve_team(team)
	sub = frappe.db.get_value(
		"Subscription",
		{"server_id": server, "team": team},
		["name", "pricing_mode", "sub_category", "plan"],
		as_dict=True,
	)
	if not sub:
		return {"resizable": False, "composed": False}

	from central.billing.catalog.subscriptions import team_run_rate

	composed = sub.pricing_mode == "Composed"
	if composed:
		includes = frappe.get_all(
			"Plan Includes",
			filters={"parenttype": "Subscription", "parent": sub.name},
			fields=["resource_type", "quantity"],
		)
		qty = composition_quantities(includes)
		vcpus, memory_gb, disk_gb = qty.get(COMPUTE, 0), qty.get(MEMORY, 0), qty.get(DISK, 0)
	else:
		# A preset carries no composition — its shape lives on the mirrored VM.
		shape = (
			frappe.db.get_value(
				"Virtual Machine", server, ["vcpus", "memory_megabytes", "disk_gigabytes"], as_dict=True
			)
			or frappe._dict()
		)
		vcpus = shape.vcpus or 0
		memory_gb = (shape.memory_megabytes or 0) / 1024
		disk_gb = shape.disk_gigabytes or 0

	cap = frappe.utils.flt(get_team_caps(team).max_spend)
	return {
		"resizable": True,
		"composed": composed,
		"subscription": sub.name,
		"sub_category": sub.sub_category,
		"plan": sub.plan,  # the current preset, so the picker can pre-select it
		"vcpus": vcpus,
		"memory_gb": memory_gb,
		"disk_gb": disk_gb,
		"available": max(0.0, cap - team_run_rate(team, exclude=sub.name)),
		# What the resize would cost this server in price terms, so the picker can
		# say it before the customer commits rather than after.
		"lock": _lock_disclosure(team, sub.name, _team_currency(team)),
	}
