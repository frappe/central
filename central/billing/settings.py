# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reading Billing Settings.

Every billing knob is read through a named function here rather than off the
document, so a caller asks for the policy ("how many days until this invoice is
due?") instead of knowing which field on which Single holds it.

The document is read with `get_cached_doc`, which applies the DocType's field
defaults when nobody has saved the Single yet. Those defaults are therefore the
real fallbacks, and they live in one place — the JSON — instead of being repeated
as constants here. The one exception is the per-currency welcome grant: child rows
can't have defaults, so `ensure_welcome_credit_amounts` seeds them on install.
"""

from contextlib import contextmanager
from contextvars import ContextVar

import frappe

SETTINGS = "Billing Settings"

# What a projection is asking "what if" about. A context variable rather than a
# parameter because the question is asked several layers down — dunning, invoicing and
# credits all read policy — and threading a settings bundle through every one of them
# would put the simulator's concerns into code that has no business knowing it exists.
#
# Nothing here writes. An override changes what a projection *reads*, never what the
# document holds, so the answer to "what would a 2/5/10 ladder do" costs nobody their
# real configuration.
_overrides: ContextVar[dict | None] = ContextVar("billing_settings_overrides", default=None)


@contextmanager
def overridden(**values):
	"""Read Billing Settings as if these values were saved, for this block only.

	Nests: an inner override wins for the fields it names and leaves the rest alone.
	"""
	merged = {**(_overrides.get() or {}), **{k: v for k, v in values.items() if v is not None}}
	token = _overrides.set(merged)
	try:
		yield merged
	finally:
		_overrides.reset(token)


def active_overrides() -> dict:
	"""What is currently being pretended, if anything — for showing on the output."""
	return dict(_overrides.get() or {})


def _override(field):
	"""The overridden value for `field`, or `_MISSING` when it is not being pretended."""
	return (_overrides.get() or {}).get(field, _MISSING)


class _Missing:
	def __bool__(self):
		return False


_MISSING = _Missing()

# The launch grant, seeded once onto a Billing Settings nobody has saved yet. It is
# a starting point for the accounts team to edit, not a value the code depends on.
LAUNCH_WELCOME_CREDITS = {"INR": 2500.0, "USD": 25.0}


def _settings():
	return frappe.get_cached_doc(SETTINGS)


def welcome_credit_amount(currency: str) -> float:
	"""What a team billed in `currency` is granted on completing its profile.

	Zero when grants are switched off or the currency has no configured amount —
	callers treat both the same way, by not granting."""
	settings = _settings()
	if not settings.grant_welcome_credits:
		return 0.0
	for row in settings.welcome_credit_amounts:
		if row.currency == currency:
			return frappe.utils.flt(row.amount)
	return 0.0


def provision_teams_as_trial() -> bool:
	"""Whether a new team is created as a staging trial — provisioning servers on
	welcome credits without a full billing profile. Off outside staging."""
	return bool(_settings().provision_teams_as_trial)


def promotional_credit_validity_days() -> int:
	"""Days a welcome credit stays usable; 0 means it never expires."""
	override = _override("promotional_credit_validity_days")
	if override is not _MISSING:
		return frappe.utils.cint(override)
	return frappe.utils.cint(_settings().promotional_credit_validity_days)


def invoice_due_days() -> int:
	"""Days between an invoice opening and falling due."""
	override = _override("invoice_due_days")
	if override is not _MISSING:
		return frappe.utils.cint(override)
	return frappe.utils.cint(_settings().invoice_due_days)


def dunning_retry_days() -> list[int]:
	"""Days past due on which payment is retried, in order. Empty means no retries."""
	override = _override("dunning_retry_days")
	if override is not _MISSING:
		return _parse_retry_days(override)
	return _settings().retry_days()


def suspend_after_days() -> int:
	"""Days past due before a subscription is suspended."""
	override = _override("suspend_after_days")
	if override is not _MISSING:
		return frappe.utils.cint(override)
	return frappe.utils.cint(_settings().suspend_after_days)


def terminate_after_days() -> int:
	"""Days past due before a subscription is terminated."""
	override = _override("terminate_after_days")
	if override is not _MISSING:
		return frappe.utils.cint(override)
	return frappe.utils.cint(_settings().terminate_after_days)


def payment_log_retention_days() -> int:
	"""Rolling window (days) the gateway logs — Payment Attempt and Webhook Event —
	are kept before daily pruning."""
	return frappe.utils.cint(_settings().payment_log_retention_days)


def default_gst_rate() -> float:
	"""Output GST rate stamped on a new Indian team's Tax Profile."""
	return frappe.utils.flt(_settings().default_gst_rate)


def forecast_notify_ratio() -> float:
	"""Share of a team's cap at which its forecast spend warning fires (0.8 = 80%)."""
	override = _override("forecast_notify_percent")
	if override is not _MISSING:
		return frappe.utils.flt(override) / 100.0
	return frappe.utils.flt(_settings().forecast_notify_percent) / 100.0


def ensure_welcome_credit_amounts() -> None:
	"""Seed the launch grant amounts if no currency has an amount yet.

	Called from install (fresh sites, where patches are skipped), before tests, and
	a one-time patch (existing sites). Each of those runs once, which is what makes
	this safe: it is a starting point, not a value re-asserted on every migrate. Were
	it re-asserted, removing a currency's grant would be undone the next time anyone
	migrated — the admin would keep losing an argument with the deploy.

	The guard is "nothing is configured", not "the Single was never saved": an admin
	who opens and saves the form before this ever runs would otherwise leave the grant
	permanently unseeded, and welcome credits would quietly stop.
	"""
	settings = frappe.get_doc(SETTINGS)
	if settings.welcome_credit_amounts:
		return

	for currency, amount in LAUNCH_WELCOME_CREDITS.items():
		settings.append("welcome_credit_amounts", {"currency": currency, "amount": amount})
	settings.save(ignore_permissions=True)


def _parse_retry_days(value) -> list[int]:
	"""Accept a ladder as a list or as the comma string the document stores."""
	if isinstance(value, str):
		parts = [p.strip() for p in value.split(",") if p.strip()]
	else:
		parts = list(value or [])
	days = []
	for part in parts:
		try:
			day = int(part)
		except (TypeError, ValueError):
			continue
		if day not in days:
			days.append(day)
	return sorted(days)
