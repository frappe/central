# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Seed the welcome credit amounts onto Billing Settings.

The grant used to be a constant in the code; it is a per-currency table on the
Single now. This carries the amounts a migrated site was already granting over, so
nothing changes for teams signing up the day of the deploy. A one-time patch rather
than a migrate hook, so removing a currency later is not undone on the next deploy.
"""

from central.billing.settings import ensure_welcome_credit_amounts


def execute():
	ensure_welcome_credit_amounts()
