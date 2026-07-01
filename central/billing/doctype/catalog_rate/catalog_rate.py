# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog Rate — one standalone rate per (priced thing, cluster, currency).

Mirrors ERPNext's `Item Price`: a single table prices both a whole `Plan` and an
individual `Resource Type`, linked via a Dynamic Link (`priced_doctype` +
`priced_for`). For a Plan the rate is the flat bundle price (or the per-unit price
of a metered single-resource Plan, ADR 0008); for a Resource Type it is the
per-unit component rate (`$/vCPU`, `$/GB`) the composed-config rate card is summed
from (ADR 0009).
"""

import frappe
from frappe.model.document import Document

# `priced_doctype` is a Dynamic Link to DocType and otherwise unconstrained, so
# validation pins it to the two things we price: a whole Plan (ADR 0008) and a
# Resource Type component for à-la-carte composed configs (ADR 0009).
ALLOWED_PARENTS = ("Plan", "Resource Type")


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
