# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing counters, emitted as one parseable JSON line each."""

import json
import time
from contextlib import contextmanager

import frappe

LOGGER = "billing"


def emit(metric: str, **fields) -> dict:
	"""Log one counter as a single JSON line a log scraper can parse."""
	record = {"metric": metric, **fields}
	frappe.logger(LOGGER).info(json.dumps(record, default=str, sort_keys=True))
	return record


@contextmanager
def timed(metric: str, **fields):
	"""Time a block and emit it on exit. Yields a dict to put counters in."""
	counters: dict = {}
	started = time.monotonic()
	outcome = "ok"
	try:
		yield counters
	except Exception:
		outcome = "error"
		raise
	finally:
		emit(
			metric,
			duration_ms=round((time.monotonic() - started) * 1000),
			outcome=outcome,
			**{**fields, **counters},
		)
