import json
from urllib.parse import unquote

import frappe
from frappe.utils import cint

from central.signups.doctype.product.product import FRAPPE_CLOUD_PRODUCT_KEY
from central.signups.doctype.product_referral.product_referral import ProductReferral

COOKIE_NAME = "central_affiliate"


def record_referral(team: str, product: str | None) -> None:
	"""Credit the affiliate whose link brought this signup for the product. A failure is logged and
	never stops the signup."""
	key = product or FRAPPE_CLOUD_PRODUCT_KEY
	visits = read_visit_cookie()
	if key not in visits:
		return

	frappe.db.savepoint("affiliate_referral")
	try:
		referral = ProductReferral.record(team, product, visits[key])
	except frappe.DuplicateEntryError:
		# Another request credited this team and product first. The first referral is final, and
		# the signup must not show Frappe's "already exists" message.
		frappe.db.rollback(save_point="affiliate_referral")
		frappe.clear_last_message()
		return
	except Exception:
		frappe.db.rollback(save_point="affiliate_referral")
		frappe.clear_last_message()
		frappe.log_error(title="Affiliate referral failed", reference_doctype="Team", reference_name=team)
		return

	frappe.db.release_savepoint("affiliate_referral")
	if referral:
		del visits[key]
		write_visit_cookie(visits)


def read_visit_cookie() -> dict[str, str]:
	"""The browser's visit for each product key. Bad data, or no request, reads as no visits."""
	request = getattr(frappe.local, "request", None)
	if not request:
		return {}

	try:
		visits = json.loads(unquote(request.cookies.get(COOKIE_NAME, "")))
	except ValueError:
		return {}

	if not isinstance(visits, dict):
		return {}

	return {key: name for key, name in visits.items() if isinstance(key, str) and isinstance(name, str)}


def write_visit_cookie(visits: dict[str, str]) -> None:
	if not visits:
		frappe.local.cookie_manager.delete_cookie(COOKIE_NAME)
		return

	days = cint(frappe.db.get_single_value("Central Settings", "affiliate_cookie_days"))
	# Frappe URL-encodes the value when it sends the cookie.
	value = json.dumps(visits, separators=(",", ":"))
	frappe.local.cookie_manager.set_cookie(COOKIE_NAME, value, max_age=days * 24 * 60 * 60, httponly=True)
