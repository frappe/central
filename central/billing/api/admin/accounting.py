# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin action for the accounting setup: check that what Central reads is there."""

import frappe

from central.billing import authz
from central.billing.ingester import setup


@frappe.whitelist()
def check_accounting_setup() -> list[dict]:
	"""What exists in the accounting system and what does not. Writes nothing."""
	authz.require_operator()
	return setup.check()
