# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from frappe.model.document import Document


class PassportRegistration(Document):
	"""Central's own record of a site it registered with Passport.

	The Site doctype is a read-only mirror of Atlas, so the registration Central owns
	lives here instead: which client id a site got, and at which origin.
	"""
