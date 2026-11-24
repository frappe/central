import frappe

from central.billing.catalog.pricing import set_catalog_rate
from central.services.doctype.team_service.team_service import find_storage_plan

# $25 a TB-month, and ₹2.5 a GB-month, rounded from about ₹93 to the dollar.
RATES = {"USD": 0.025, "INR": 2.5}


def execute():
	"""Price object storage per GB-month; a rate an operator already set above 0 is kept."""
	plan = find_storage_plan()
	if not plan:
		return
	for currency, rate in RATES.items():
		_price(plan, currency, rate)


def _price(plan: str, currency: str, rate: float) -> None:
	# A rate of 0 was a placeholder from before storage was billed, so it gets the starting rate.
	rows = frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": "Plan", "priced_for": plan, "currency": currency},
		fields=["name", "cluster", "rate"],
	)
	if any(row.rate > 0 for row in rows):
		return
	if not rows:
		set_catalog_rate("Plan", plan, currency, rate)
	for row in rows:
		set_catalog_rate("Plan", plan, currency, rate, cluster=row.cluster)
