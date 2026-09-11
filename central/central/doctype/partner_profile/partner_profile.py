# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import secrets
import string

import frappe
from frappe.model.document import Document

# One-time, permanent code a customer enters to request a link with this
# partner. 12 chars over a 36-symbol alphabet (~62 bits) — collisions are
# checked for defensively but effectively impossible at this length.
PARTNER_CODE_LENGTH = 12
PARTNER_CODE_ALPHABET = string.ascii_uppercase + string.digits


class PartnerProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		connect_partner: DF.Data
		partner_code: DF.Data
		team: DF.Link
	# end: auto-generated types

	def before_insert(self) -> None:
		if not self.partner_code:
			self.partner_code = self._generate_partner_code()

	@staticmethod
	def _generate_partner_code() -> str:
		while True:
			code = "".join(secrets.choice(PARTNER_CODE_ALPHABET) for _ in range(PARTNER_CODE_LENGTH))
			if not frappe.db.exists("Partner Profile", {"partner_code": code}):
				return code
