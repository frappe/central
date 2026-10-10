import frappe
from frappe.rate_limiter import rate_limit


# nosemgrep: guest-whitelisted-method -- returns public branding only, limited by IP.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_product(product: str) -> dict | None:
	"""The branding the signup pages show for a product. None when it is unknown or disabled."""
	# A guest reads this before signing in, and it holds nothing but public branding.
	return frappe.db.get_value(
		"Product", {"name": product, "enabled": 1}, ["title", "logo", "subtitle"], as_dict=True
	)
