# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TrustTierLevel(Document):
	def validate(self):
		self._validate_unique_currencies()
		self._validate_entry_tier_coverage()

	def _validate_unique_currencies(self):
		"""One threshold row per currency — a tier can't carry two caps for INR."""
		seen = set()
		for row in self.thresholds:
			if row.currency in seen:
				frappe.throw(_("Duplicate threshold for currency {0}.").format(row.currency))
			seen.add(row.currency)

	def _validate_entry_tier_coverage(self):
		"""The entry tier is where every team lands, so it must price every
		currency a team can be billed in — otherwise a team in that currency has
		no floor (and no resolvable cap)."""
		if not self.is_default:
			return
		from central.billing.gateways.registry import supported_currencies

		covered = {row.currency for row in self.thresholds}
		missing = [c for c in supported_currencies() if c not in covered]
		if missing:
			frappe.throw(
				_("The entry tier must define a threshold for every supported currency. Missing: {0}").format(
					", ".join(missing)
				)
			)
