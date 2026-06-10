# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Dashboard connections added to core DocTypes (via override_doctype_dashboards)."""


def currency_dashboard(data):
	"""Surface the Catalog Rates priced in a Currency on the Currency form."""
	data["transactions"].append({"label": "Billing", "items": ["Catalog Rate"]})
	data.setdefault("non_standard_fieldnames", {})["Catalog Rate"] = "currency"
	return data
