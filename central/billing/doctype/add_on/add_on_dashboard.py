# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Connections shown on the Add-on form — its rates."""


def get_data():
	return {
		"fieldname": "priced_for",
		"transactions": [
			{"label": "Pricing", "items": ["Catalog Rate"]},
		],
	}
