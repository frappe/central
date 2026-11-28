# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.caching import request_cache

from central.billing import settings
from central.billing.revenue.exchange_rate_feed import feed_rate
from central.billing.revenue.usage_ledger import utc_today

DOCTYPE = "Monthly Exchange Rate"
READING_KEY = "billing_month_rate_reading"
READING_SECONDS = 60 * 60
MISS_SECONDS = 5 * 60


def month_rate(from_currency: str, to_currency: str, on, fresh: bool = False) -> frappe._dict:
	"""The rate a month converts `from_currency` at, as {rate, rate_date, fixed}. Reads only."""
	# The Overview, the recount and the invoice all use this one rate for the month.
	if from_currency == to_currency:
		return frappe._dict(rate=1.0, rate_date=None, fixed=True)
	key = month_key(from_currency, to_currency, on)
	return stored_rate(key) or frappe._dict(_reading(key, fresh), fixed=False)


def fix_month_rate(from_currency: str, to_currency: str, on, final: bool = False) -> frappe._dict:
	"""The month's rate, stored from the month's 2nd (UTC), or with `final` whatever is found."""
	# The final read skips the cache, so the draft keeps what the rate API gives now.
	found = month_rate(from_currency, to_currency, on, fresh=final)
	key = month_key(from_currency, to_currency, on)
	if found.fixed or not _is_to_keep(key, found, final):
		return found
	return _store(key, found)


def keep_report_rate(month) -> None:
	"""Keep a closed month's USD to INR rate, so the reports convert that month at it."""
	try:
		fix_month_rate("USD", "INR", month, final=True)
	except frappe.ValidationError:
		# The reports fall back to the nearest kept month, and the run must still draft.
		frappe.log_error(title="USD to INR rate not kept", message=frappe.get_traceback())


def report_usd_to_inr(on=None) -> float:
	"""The USD to INR rate the margin reports and dashboards use for the month of `on`. Reads only.

	1. The rate set in Billing Settings, when one is set.
	2. Else the kept rate of that month, or of the nearest month before it.
	3. Else the earliest kept rate, for a month before any rate was kept.
	4. Else 0, and the reports leave USD out.
	"""
	return settings.reporting_usd_to_inr() or _kept_usd_to_inr(month_key("USD", "INR", on)["month"])


@request_cache
def _kept_usd_to_inr(month) -> float:
	pair = {"from_currency": "USD", "to_currency": "INR"}
	for month_filter, order_by in ((["<=", month], "month desc"), ([">", month], "month asc")):
		rate = frappe.db.get_value(DOCTYPE, {**pair, "month": month_filter}, "rate", order_by=order_by)
		if rate:
			return frappe.utils.flt(rate)
	return 0.0


def _is_to_keep(key: dict, found: frappe._dict, final: bool) -> bool:
	# On the 1st the API may still give the last day's rate; by the 2nd it has the 1st's.
	# An earlier month's rate stands in only for the draft, so the API's own rate can still come.
	return final or (not found.is_fallback and utc_today() > key["month"])


def stored_rate(key: dict) -> frappe._dict | None:
	"""The rate kept for a month, if one was."""
	stored = frappe.db.get_value(DOCTYPE, key, ["rate", "rate_date"], as_dict=True)
	return frappe._dict(stored, fixed=True) if stored else None


def _earlier_rate(key: dict) -> frappe._dict | None:
	earlier = frappe.db.get_value(
		DOCTYPE,
		{
			"from_currency": key["from_currency"],
			"to_currency": key["to_currency"],
			"month": ["<", key["month"]],
		},
		["month", "rate", "rate_date"],
		as_dict=True,
		order_by="month desc",
	)
	if not earlier:
		return None
	return frappe._dict(
		rate=earlier.rate,
		rate_date=earlier.rate_date,
		source=f"fallback: {earlier.month:%Y-%m}",
		is_fallback=True,
	)


def month_key(from_currency: str, to_currency: str, on) -> dict:
	"""The filters of a month's stored rate."""
	month = frappe.utils.getdate(on).replace(day=1)
	return {"month": month, "from_currency": from_currency, "to_currency": to_currency}


def _reading(key: dict, fresh: bool) -> frappe._dict:
	"""The rate for an unstored month, cached for an hour."""
	# Each rollup of the month reads it every hour, so one call serves them all.
	cache_key = reading_key(key)
	if not fresh and (cached := frappe.cache.get_value(cache_key, expires=True)):
		return frappe._dict(cached)
	found = _required_rate(key, fresh)
	frappe.cache.set_value(cache_key, dict(found), expires_in_sec=READING_SECONDS)
	return found


def reading_key(key: dict) -> str:
	"""The cache key of a month's unstored reading."""
	return f"{READING_KEY}:{key['from_currency']}:{key['to_currency']}:{key['month']}"


def _required_rate(key: dict, fresh: bool) -> frappe._dict:
	found = _feed_rate(key, fresh) or _earlier_rate(key)
	if not found:
		frappe.throw(
			_("The rate API gave no {0} to {1} rate for {2} and no earlier month's rate is kept.").format(
				key["from_currency"], key["to_currency"], key["month"]
			)
		)
	return found


def _feed_rate(key: dict, fresh: bool) -> frappe._dict | None:
	# A down API can take the full timeout on each read, so a miss is not asked again for a while.
	miss_key = f"{reading_key(key)}:miss"
	if not fresh and frappe.cache.get_value(miss_key, expires=True):
		return None
	found = feed_rate(key["from_currency"], key["to_currency"], key["month"])
	if not found:
		frappe.cache.set_value(miss_key, 1, expires_in_sec=MISS_SECONDS)
	return found


def _store(key: dict, found: frappe._dict) -> frappe._dict:
	try:
		frappe.db.savepoint("monthly_exchange_rate")
		# Written by billing on the first read of the month; Desk only reads it.
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				**key,
				"rate": found.rate,
				"rate_date": found.rate_date,
				"source": found.source,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Another worker stored the month first. Its rate is the month's, even if this read differs.
		frappe.db.rollback(save_point="monthly_exchange_rate")
		stored = frappe.db.get_value(DOCTYPE, key, ["rate", "rate_date"], as_dict=True, for_update=True)
		# The other worker's row can be gone again if it rolled back; then this reading stays unstored.
		return frappe._dict(stored, fixed=True) if stored else found
	return frappe._dict(found, fixed=True)
