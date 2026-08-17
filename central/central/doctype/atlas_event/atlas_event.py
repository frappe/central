# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password


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

	def verify_signature(self) -> bool:
		"""Re-check this stored row against the signature it was admitted on. False for a row
		predating capture, or whose cluster was re-registered — rotation isn't tampering."""
		if not (self.raw_body and self.signature and self.signature_timestamp):
			return False

		from central.integrations.atlas import signature_matches

		secret = get_decrypted_password(
			"Atlas Instance", self.cluster, "webhook_secret", raise_exception=False
		)
		if not secret:
			return False
		return signature_matches(secret, self.signature_timestamp, self.raw_body.encode(), self.signature)
