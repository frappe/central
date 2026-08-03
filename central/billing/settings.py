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

import frappe

SETTINGS = "Billing Settings"

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


def promotional_credit_validity_days() -> int:
	"""Days a welcome credit stays usable; 0 means it never expires."""
	return frappe.utils.cint(_settings().promotional_credit_validity_days)


def invoice_due_days() -> int:
	"""Days between an invoice opening and falling due."""
	return frappe.utils.cint(_settings().invoice_due_days)


def dunning_retry_days() -> list[int]:
	"""Days past due on which payment is retried, in order. Empty means no retries."""
	return _settings().retry_days()


def suspend_after_days() -> int:
	"""Days past due before a subscription is suspended."""
	return frappe.utils.cint(_settings().suspend_after_days)


def terminate_after_days() -> int:
	"""Days past due before a subscription is terminated."""
	return frappe.utils.cint(_settings().terminate_after_days)


def default_gst_rate() -> float:
	"""Output GST rate stamped on a new Indian team's Tax Profile."""
	return frappe.utils.flt(_settings().default_gst_rate)


def forecast_notify_ratio() -> float:
	"""Share of a team's cap at which its forecast spend warning fires (0.8 = 80%)."""
	return frappe.utils.flt(_settings().forecast_notify_percent) / 100.0


def ensure_welcome_credit_amounts() -> None:
	"""Seed the launch grant amounts, once, on a Billing Settings nobody has saved.

	Runs on install and on every migrate, so a fresh site and an existing one both
	end up configured. It deliberately does nothing once the Single has been saved:
	re-adding a currency an admin removed would quietly undo their decision, and
	overwriting an amount they changed would undo it every migrate.
	"""
	if frappe.db.count("Singles", {"doctype": SETTINGS}):
		return

	settings = frappe.get_doc(SETTINGS)
	for currency, amount in LAUNCH_WELCOME_CREDITS.items():
		settings.append("welcome_credit_amounts", {"currency": currency, "amount": amount})
	settings.save(ignore_permissions=True)
