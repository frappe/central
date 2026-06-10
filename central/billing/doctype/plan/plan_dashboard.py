# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Connections shown on the Plan form — its rates and its price-locks."""


def get_data():
	return {
		"fieldname": "priced_for",
		"non_standard_fieldnames": {
			"Price Lock": "plan",
		},
		"transactions": [
			{"label": "Pricing", "items": ["Catalog Rate"]},
			{"label": "Provisioning", "items": ["Price Lock"]},
		],
	}
