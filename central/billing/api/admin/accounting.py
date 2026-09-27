# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin actions on Accounting Settings: check the setup, create what is missing."""

import frappe

from central.billing import authz
from central.billing.ingester import setup


@frappe.whitelist()
def check_accounting_setup() -> list[dict]:
	"""What exists in the accounting system and what does not. Writes nothing."""
	authz.require_operator()
	return setup.check()


@frappe.whitelist(methods=["POST"])
def create_missing_accounting_setup() -> list[dict]:
	"""Create the missing records and fill blank settings. Changes nothing already set."""
	authz.require_operator()
	return setup.create_missing()
