# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a server's plan includes is its bundle: usage of the same resource above it bills.

A meter records each day what was used and what the plan included that day. A held amount
(GB stored, addresses kept) bills each day above that day's bundle; an amount used up
(transfer) bills the month above the bundle, scaled to the days the plan ran.
"""

import frappe


class Bundles:
	"""The included quantity of one resource on billing segments, preset or composed."""

	def __init__(self, resource_type: str, segments: list):
		self.resource_type = resource_type
		self.by_plan = _included(resource_type, "Plan", {s.plan for s in segments if s.plan})
		# A composed segment names no plan. Its change row keeps what it included; a row written
		# before rows kept it, or a segment open now, takes the subscription's own.
		composed = {s.subscription for s in segments if not (s.plan or s.get("included_resources"))}
		self.by_subscription = _included(resource_type, "Subscription", composed)

	def of(self, segment) -> float:
		"""What `segment` includes of the resource, 0 when nothing."""
		if segment.plan:
			return self.by_plan.get(segment.plan, 0)
		if segment.get("included_resources"):
			return _recorded(self.resource_type, segment.included_resources)
		return self.by_subscription.get(segment.subscription, 0)


def _recorded(resource_type: str, included_resources) -> float:
	"""The resource's quantity in a change row's kept includes, 0 when none."""
	rows = frappe.parse_json(included_resources) or []
	return next(
		(frappe.utils.flt(row.get("quantity")) for row in rows if row.get("resource_type") == resource_type),
		0,
	)


def _included(resource_type: str, parenttype: str, parents: set) -> dict[str, float]:
	if not parents:
		return {}
	rows = frappe.get_all(
		"Plan Includes",
		filters={
			"parenttype": parenttype,
			"parent": ["in", list(parents)],
			"resource_type": resource_type,
			"quantity": [">", 0],
		},
		fields=["parent", "quantity"],
	)
	return {row.parent: frappe.utils.flt(row.quantity) for row in rows}
