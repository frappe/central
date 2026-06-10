# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Append-only grandfathering lock.

A lock is a historical fact: once written its rate never changes (live catalog
edits do not touch existing locks). The controller forbids editing the locked
rate after creation; `ended_at` — closing a segment on terminate/reprovision —
is set via `frappe.db.set_value`, bypassing the document layer.
"""

import frappe
from frappe.model.document import Document

_IMMUTABLE = ("resource_id", "locked_rate", "currency", "plan", "cluster", "source_event_id")


class PriceLock(Document):
	def validate(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		for field in _IMMUTABLE:
			if self.get(field) != before.get(field):
				frappe.throw(
					f"Price Lock is append-only; '{field}' cannot change after lock.",
					frappe.ValidationError,
				)
