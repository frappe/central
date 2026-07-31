# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How long a gateway webhook waits before we act on it.

A webhook is the only thing that settles an invoice, so lag here is lag on every
customer's payment showing as paid. Measured from the moment we received the event to
the moment we finished processing it.
"""

import frappe
from frappe import _
from frappe.utils import flt

# Above this, settlement is late enough that a customer could notice.
SLOW_SECONDS = 60


def execute(filters: dict | None = None):
	filters = filters or {}
	events = _events(filters)
	rows = _by_gateway_and_day(events)
	return _columns(), rows, _message(rows), _chart(rows), _summary(events)


def _events(filters: dict) -> list[dict]:
	conditions = {"processed_at": ["is", "set"]}
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
		fields=["gateway", "creation", "processed_at", "status"],
		limit_page_length=0,
	)


def _lag_seconds(event) -> float:
	return frappe.utils.time_diff_in_seconds(event.processed_at, event.creation)


def _by_gateway_and_day(events: list[dict]) -> list[dict]:
	buckets: dict[tuple, list[float]] = {}
	for e in events:
		buckets.setdefault((e.gateway, frappe.utils.getdate(e.creation)), []).append(_lag_seconds(e))

	rows = []
	for (gateway, day), lags in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[0][0]), reverse=True):
		ordered = sorted(lags)
		rows.append(
			{
				"day": day,
				"gateway": gateway,
				"events": len(ordered),
				"median_seconds": flt(_percentile(ordered, 0.5), 2),
				"p95_seconds": flt(_percentile(ordered, 0.95), 2),
				"worst_seconds": flt(ordered[-1], 2),
				"slow": sum(1 for lag in ordered if lag > SLOW_SECONDS),
			}
		)
	return rows


def _percentile(ordered: list[float], fraction: float) -> float:
	"""Nearest-rank percentile of an already-sorted list."""
	if not ordered:
		return 0.0
	index = min(int(round(fraction * len(ordered) + 0.5)) - 1, len(ordered) - 1)
	return ordered[index]


def _columns() -> list[dict]:
	return [
		{"label": _("Day"), "fieldname": "day", "fieldtype": "Date", "width": 110},
		{"label": _("Gateway"), "fieldname": "gateway", "fieldtype": "Link", "options": "Payment Gateway", "width": 160},
		{"label": _("Events"), "fieldname": "events", "fieldtype": "Int", "width": 90},
		{"label": _("Median (s)"), "fieldname": "median_seconds", "fieldtype": "Float", "width": 110},
		{"label": _("p95 (s)"), "fieldname": "p95_seconds", "fieldtype": "Float", "width": 110},
		{"label": _("Worst (s)"), "fieldname": "worst_seconds", "fieldtype": "Float", "width": 110},
		{"label": _("Slow"), "fieldname": "slow", "fieldtype": "Int", "width": 90},
	]


def _message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No processed webhooks in this window.")
	return _("Lag is measured from receipt to the end of processing. 'Slow' counts events over {0}s.").format(
		SLOW_SECONDS
	)


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	ordered = sorted(rows, key=lambda r: r["day"])
	return {
		"data": {
			"labels": [str(r["day"]) for r in ordered],
			"datasets": [{"name": _("p95 seconds"), "values": [r["p95_seconds"] for r in ordered]}],
		},
		"type": "line",
	}


def _summary(events: list[dict]) -> list[dict]:
	lags = sorted(_lag_seconds(e) for e in events)
	p95 = _percentile(lags, 0.95)
	return [
		{"label": _("Events"), "value": len(lags), "datatype": "Int"},
		{
			"label": _("p95 Lag (s)"),
			"value": flt(p95, 2),
			"datatype": "Float",
			"indicator": "green" if p95 <= SLOW_SECONDS else "red",
		},
		{"label": _("Slow Events"), "value": sum(1 for lag in lags if lag > SLOW_SECONDS), "datatype": "Int"},
	]
