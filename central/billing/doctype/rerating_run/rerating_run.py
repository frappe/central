# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rerating Run — the audit record of one bulk re-issue."""

import frappe
from frappe.model.document import Document

from central.billing.states import transition


class ReratingRun(Document):
	def before_insert(self):
		self.started_at = self.started_at or frappe.utils.now_datetime()

	def finish(self, state: str) -> None:
		"""Close the run out. `state` is Complete or Failed."""
		transition(self, state, reason=self.reason, actor=frappe.session.user)
		self.completed_at = frappe.utils.now_datetime()
		self.save(ignore_permissions=True)
