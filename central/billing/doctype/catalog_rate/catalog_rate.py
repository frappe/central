# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog Rate — one standalone rate per (Plan|Add-on, cluster, currency).

Mirrors ERPNext's `Item Price`: a single table prices every bundle and every
add-on, linked via a Dynamic Link (`priced_doctype` + `priced_for`). The rate is
the flat price for a Plan and the per-unit price for an Add-on.
"""

import frappe
from frappe.model.document import Document

# `priced_doctype` is restricted to these two via validation (a Dynamic Link to
# DocType is otherwise unconstrained).
ALLOWED_PARENTS = ("Plan", "Add-on")


class CatalogRate(Document):
	def autoname(self):
		# {priced_for}-{cluster}-{currency}; cluster omitted when global.
		parts = [self.priced_for, (self.cluster or "").strip() or None, self.currency]
		self.name = "-".join(p for p in parts if p)

	def validate(self):
		if self.priced_doctype not in ALLOWED_PARENTS:
			frappe.throw(
				f"Priced Doctype must be one of {', '.join(ALLOWED_PARENTS)}, not {self.priced_doctype!r}."
			)
		# Normalise a blank cluster to None so "global" rows compare cleanly.
		if not (self.cluster or "").strip():
			self.cluster = None
