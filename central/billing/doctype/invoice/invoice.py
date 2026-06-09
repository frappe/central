# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Invoice — postpaid, in-arrears, immutable once issued.

Naming is INV-YYYY-MM-NNNNN keyed on the billing month (period_end). Line items
are generated once and never updated; corrections are by state (cancel+reissue
before payment; refund / wallet credit after), never by mutation.
"""

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class Invoice(Document):
	def autoname(self):
		month = frappe.utils.getdate(self.period_end or frappe.utils.nowdate())
		self.name = make_autoname(f"INV-{month.year:04d}-{month.month:02d}-.#####")
