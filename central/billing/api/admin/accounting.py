# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin actions for the accounting system: check the setup, and send records by hand."""

import frappe

from central.billing import authz
from central.billing.ingester import setup


@frappe.whitelist()
def check_accounting_setup() -> list[dict]:
	"""What exists in the accounting system and what does not. Writes nothing."""
	authz.require_operator()
	return setup.check()


@frappe.whitelist()
def get_manual_setup_gaps() -> list[dict]:
	"""The Billing Settings values an operator must set by hand, for the workspace banner."""
	from central.billing.platform import readiness

	authz.require_operator()
	return [{"check": gap.check, "detail": gap.detail} for gap in readiness.get_manual_setup_gaps()]


@frappe.whitelist(methods=["GET"])
def preview_accounting_push(doctype: str, name: str) -> dict:
	"""What sending this record to the accounting system would post. Writes nothing."""
	from central.billing.ingester import push

	authz.require_operator()
	return push.preview(doctype, name)


@frappe.whitelist(methods=["POST"])
def push_to_accounting(doctype: str, name: str) -> dict:
	"""Send this record, and what it needs first, to the accounting system now."""
	from central.billing.ingester import push

	authz.require_operator()
	return push.push(doctype, name)
