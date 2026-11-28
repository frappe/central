import frappe
from frappe import _

from central.signups.affiliate_link import get_cookie_days
from central.signups.affiliate_performance import get_performance
from central.signups.doctype.affiliate.affiliate import Affiliate


@frappe.whitelist(methods=["GET"])
def get_affiliate() -> dict:
	"""The signed-in user's affiliate, or None if they are not in the affiliate program. Also returns
	cookie_days, the enabled products, and every source with whether Make a link offers it."""
	return {
		"affiliate": Affiliate.get_user_affiliate(frappe.session.user),
		"cookie_days": get_cookie_days(),
		# The enabled product list is public catalog data, and Central User has no read on Product.
		"products": frappe.get_all(
			"Product", filters={"enabled": 1}, fields=["name", "title"], order_by="title asc"
		),
		# Public catalog data that Central User cannot read. Disabled sources are kept, so
		# signups that used one still show its name.
		"sources": frappe.get_all(
			"Affiliate Source", fields=["name", "title", "enabled"], order_by="title asc"
		),
	}


@frappe.whitelist(methods=["POST"])
def set_affiliate_program(joined: bool) -> dict:
	"""Join or leave the affiliate program as the signed-in user."""
	Affiliate.set_membership(frappe.session.user, joined)
	return get_affiliate()


@frappe.whitelist(methods=["GET"])
def get_affiliate_performance(period: str = "90d", product: str | None = None) -> dict:
	"""Counts for the teams the signed-in user's affiliate referred. Never names a team."""
	affiliate = frappe.db.get_value("Affiliate", {"user": frappe.session.user})
	if not affiliate:
		frappe.throw(_("Join the affiliate program to see how your links perform."), frappe.PermissionError)

	return get_performance(affiliate, period, product)
