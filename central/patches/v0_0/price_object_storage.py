import frappe

from central.billing.catalog.pricing import set_catalog_rate
from central.services.doctype.team_service.team_service import find_storage_plan

# $25 a TB-month, and ₹2.5 a GB-month, rounded from about ₹93 to the dollar.
RATES = {"USD": 0.025, "INR": 2.5}


def execute():
	"""Price object storage per GB-month; a rate an operator already set is kept."""
	plan = find_storage_plan()
	if not plan:
		return
	for currency, rate in RATES.items():
		priced = {"priced_doctype": "Plan", "priced_for": plan, "currency": currency}
		if not frappe.db.exists("Catalog Rate", priced):
			set_catalog_rate("Plan", plan, currency, rate)
