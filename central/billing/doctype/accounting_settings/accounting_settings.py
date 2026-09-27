# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The names Central uses in the accounting system.

Usable only while the accounting sync is on. Read it through `ingester.setup`.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.ingester.connection import enabled


class AccountingSettings(Document):
	def onload(self):
		self.set_onload("sync_enabled", enabled())

	def validate(self):
		if not enabled():
			frappe.throw(_("Turn on the accounting sync before changing Accounting Settings."))
