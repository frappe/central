# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


class Addon(Document):
	def get_rate(self, currency: str, cluster: str | None = None):
		"""Resolved per-unit rate for (currency, cluster). Billed as rate x quantity."""
		return resolve_rate(get_catalog_rates("Add-on", self.name), currency, cluster)
