from __future__ import annotations

import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
	"""Boot data for the previous Central dashboard SPA."""
	context.no_cache = 1
	boot = context.boot or frappe._dict()
	boot["csrf_token"] = get_csrf_token()
	boot["user"] = frappe.session.user
	context.boot = boot
	return context
