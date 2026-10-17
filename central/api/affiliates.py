import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from central.signups.affiliates.retention import get_affiliate_retention
from central.signups.affiliates.summary import get_affiliate_summary
from central.signups.doctype.affiliate.affiliate import Affiliate
from central.signups.doctype.affiliate_link.affiliate_link import AffiliateLink


@frappe.whitelist(methods=["POST"])
def apply() -> dict:
	"""Ask to become an affiliate. Safe to repeat."""
	return Affiliate.request_for(frappe.session.user).get_state()


@frappe.whitelist(methods=["GET"])
def get_affiliate() -> dict | None:
	"""The caller's own affiliate account, or None when they never applied."""
	name = frappe.db.get_value("Affiliate", {"user": frappe.session.user}, "name")
	return frappe.get_doc("Affiliate", name).get_state() if name else None


@frappe.whitelist(methods=["GET"])
def get_summary(from_date: str, to_date: str) -> dict:
	"""The caller's own funnel for the dates, both included."""
	return get_affiliate_summary(get_active_affiliate(), from_date, to_date)


@frappe.whitelist(methods=["GET"])
def get_retention() -> dict:
	"""How long the caller's paying customers keep paying."""
	return get_affiliate_retention(get_active_affiliate())


@frappe.whitelist(methods=["GET"])
def get_links() -> list[dict]:
	"""The caller's named links, newest first."""
	# An affiliate holds no permission on links, so the read filters on the caller's own affiliate.
	return frappe.get_all(
		"Affiliate Link",
		filters={"affiliate": get_active_affiliate()},
		fields=["slug", "product", "utm_source", "utm_campaign", "creation"],
		order_by="creation desc",
	)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=60 * 60, user_based=True)
def create_link(
	slug: str | None = None,
	product: str | None = None,
	utm_source: str | None = None,
	utm_campaign: str | None = None,
) -> dict:
	"""Add a named link for the caller, such as /r/bwh. An empty slug gets a random one."""
	link = AffiliateLink.create_for(get_active_affiliate(), slug, product, utm_source, utm_campaign)
	return {"slug": link.slug}


@frappe.whitelist(methods=["GET"])
def get_link_products() -> list[dict]:
	"""The enabled products an affiliate link can name, for the link builder."""
	# The enabled catalog is public, and an affiliate holds no permission on Product.
	return frappe.get_all("Product", filters={"enabled": 1}, fields=["name", "title"], order_by="title asc")


def get_active_affiliate() -> str:
	"""The caller's Active affiliate. Every other caller is refused."""
	affiliate = frappe.db.get_value("Affiliate", {"user": frappe.session.user, "status": "Active"}, "name")
	if not affiliate:
		frappe.throw(_("Only an active affiliate can do this."), frappe.PermissionError)

	return affiliate
