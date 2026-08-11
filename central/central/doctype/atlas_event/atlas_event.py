# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AtlasEvent(Document):
	def after_insert(self):
		"""Queue the mirror write once the row is durably committed, so the inbound
		webhook gets a fast ack and processing survives a lost immediate job."""
		frappe.enqueue(
			"central.integrations.atlas.apply_event",
			queue="short",
			enqueue_after_commit=True,
			event_name=self.name,
		)
