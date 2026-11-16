# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How late gateway webhooks reach us, and how long we take to act on them.

A webhook settles an invoice or a top-up when the checkout callback did not, so lag here
is lag on a customer's payment showing as paid. Delivery delay runs from the gateway
raising the event to our receiving it; processing lag from receiving it to finishing.
"""

import frappe
from frappe import _
from frappe.utils import flt

# Above this, a payment is late enough that a customer could notice.
SLOW_SECONDS = 60
# Events we have finished with. A Received event is still waiting for its job.
FINISHED = ("Processed", "Failed", "Ignored")


def execute(filters: dict | None = None):
	filters = filters or {}
	events = _events(filters)
	rows = _by_gateway_and_day(events)
	return _columns(), rows, _message(rows), _chart(rows), _summary(events)


def _events(filters: dict) -> list[dict]:
	conditions = {"status": ["in", FINISHED]}
	if filters.get("gateway"):
		conditions["gateway"] = filters["gateway"]
	if filters.get("from_date"):
		conditions["creation"] = [">=", filters["from_date"]]
	if filters.get("to_date"):
		conditions["creation"] = (
			["between", [filters["from_date"], filters["to_date"]]]
			if filters.get("from_date")
			else ["<=", filters["to_date"]]
		)
	return frappe.get_all(
		"Webhook Event",
		filters=conditions,
		fields=["gateway", "creation", "processed_at", "occurred_at", "status", "deliveries"],
		limit_page_length=0,
	)


def _lag_seconds(event) -> float | None:
	"""Receipt to the end of processing; None for an event that failed before finishing."""
	if not event.processed_at:
		return None
	return frappe.utils.time_diff_in_seconds(event.processed_at, event.creation)


def _delivery_seconds(event) -> float | None:
	"""The gateway raising the event to our receiving it; None when the gateway gave no time.
	A small clock difference between the gateway and us is read as no delay."""
	if not event.occurred_at:
		return None
	return max(frappe.utils.time_diff_in_seconds(event.creation, event.occurred_at), 0.0)


def _by_gateway_and_day(events: list[dict]) -> list[dict]:
	buckets: dict[tuple, list[dict]] = {}
	for e in events:
		buckets.setdefault((e.gateway, frappe.utils.getdate(e.creation)), []).append(e)
	return [
		{"day": day, "gateway": gateway, **_row(group)}
		for (gateway, day), group in sorted(
			buckets.items(), key=lambda kv: (kv[0][1], kv[0][0]), reverse=True
		)
	]


def _row(events: list[dict]) -> dict:
	delivery = _stats(events, _delivery_seconds)
	processing = _stats(events, _lag_seconds)
	return {
		"events": len(events),
		**{f"delivery_{key}_seconds": delivery[key] for key in ("median", "p95", "worst")},
		"delivered_late": delivery["over"],
		**{f"{key}_seconds": processing[key] for key in ("median", "p95", "worst")},
		"slow": processing["over"],
		"failed": sum(1 for e in events if e.status == "Failed"),
		"repeat_deliveries": sum(max((e.deliveries or 1) - 1, 0) for e in events),
	}


def _stats(events: list[dict], seconds_of) -> dict:
	"""Median, p95, worst and the count over the threshold, of the times that are known.
	With no known time the median, p95 and worst are blank, not zero."""
	ordered = sorted(value for value in (seconds_of(e) for e in events) if value is not None)
	over = sum(1 for value in ordered if value > SLOW_SECONDS)
	if not ordered:
		return {"median": None, "p95": None, "worst": None, "over": over}
	return {
		"median": flt(_percentile(ordered, 0.5), 2),
		"p95": flt(_percentile(ordered, 0.95), 2),
		"worst": flt(ordered[-1], 2),
		"over": over,
	}


def _percentile(ordered: list[float], fraction: float) -> float:
	"""Nearest-rank percentile of an already-sorted list."""
	if not ordered:
		return 0.0
	index = min(round(fraction * len(ordered) + 0.5) - 1, len(ordered) - 1)
	return ordered[index]


def _columns() -> list[dict]:
	return [
		{"label": _("Day"), "fieldname": "day", "fieldtype": "Date", "width": 110},
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 140,
		},
		{"label": _("Events"), "fieldname": "events", "fieldtype": "Int", "width": 80},
		*_seconds_columns(_("Delivery"), "delivery_"),
		{"label": _("Delivered Late"), "fieldname": "delivered_late", "fieldtype": "Int", "width": 120},
		{"label": _("Repeat Deliveries"), "fieldname": "repeat_deliveries", "fieldtype": "Int", "width": 130},
		*_seconds_columns(_("Processing"), ""),
		{"label": _("Slow"), "fieldname": "slow", "fieldtype": "Int", "width": 80},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 80},
	]


def _seconds_columns(stage: str, prefix: str) -> list[dict]:
	return [
		{
			"label": _("{0} {1} (s)").format(stage, label),
			"fieldname": f"{prefix}{key}_seconds",
			"fieldtype": "Float",
			"width": 140,
		}
		for label, key in ((_("Median"), "median"), (_("p95"), "p95"), (_("Worst"), "worst"))
	]


def _message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No finished webhooks in this window.")
	return _(
		"Delivery runs from the gateway raising the event to our receiving it, and processing from receipt to the end of processing. Late and Slow count events over {0}s. Repeat deliveries count the gateway sending an event again."
	).format(SLOW_SECONDS)


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	ordered = sorted(rows, key=lambda r: r["day"])
	return {
		"data": {
			"labels": [str(r["day"]) for r in ordered],
			"datasets": [
				{
					"name": _("Delivery p95 seconds"),
					"values": [r["delivery_p95_seconds"] or 0 for r in ordered],
				},
				{"name": _("Processing p95 seconds"), "values": [r["p95_seconds"] or 0 for r in ordered]},
			],
		},
		"type": "line",
	}


def _summary(events: list[dict]) -> list[dict]:
	row = _row(events)
	return [
		{"label": _("Events"), "value": row["events"], "datatype": "Int"},
		_seconds_indicator(_("p95 Delivery (s)"), row["delivery_p95_seconds"]),
		_seconds_indicator(_("p95 Processing (s)"), row["p95_seconds"]),
		_count_indicator(_("Delivered Late"), row["delivered_late"], "orange"),
		_count_indicator(_("Failed"), row["failed"], "red"),
	]


def _count_indicator(label: str, value: int, problem_color: str) -> dict:
	return {
		"label": label,
		"value": value,
		"datatype": "Int",
		"indicator": problem_color if value else "green",
	}


def _seconds_indicator(label: str, value: float | None) -> dict:
	summary = {"label": label, "value": value, "datatype": "Float"}
	if value is not None:
		summary["indicator"] = "green" if value <= SLOW_SECONDS else "orange"
	return summary
