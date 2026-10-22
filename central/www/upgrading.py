from urllib.parse import urlencode

import frappe

from central.infrastructure.doctype.site.plan_change import PlanChange

no_cache = 1


def get_context(context):
	"""The public page that follows a site's plan change, opened from a signed link. A
	developer bench also serves `?preview=1`, which plays every state with sample data."""
	context.no_cache = 1
	context.build_version = frappe.utils.get_build_version()
	context.preview = bool(frappe.conf.developer_mode and frappe.form_dict.preview)
	context.progress = None
	context.query = ""
	if context.preview:
		return

	action, site, signature = (frappe.form_dict.get(key) for key in ("action", "site", "_signature"))
	if not (action and site and signature):
		return

	try:
		change = PlanChange.from_signed_link(action, site, signature)
	except (frappe.PermissionError, frappe.DoesNotExistError):
		return

	context.progress = frappe.as_json(change.get_progress())
	context.query = urlencode({"action": action, "site": site, "signature": signature})
