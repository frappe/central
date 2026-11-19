# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebhookEvent(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("Webhook Event", ["payment_attempt"])
	frappe.db.add_index("Webhook Event", ["payment_method"])
	# The telemetry gauges read waiting and failed events each minute.
	frappe.db.add_index("Webhook Event", ["status", "modified"])
