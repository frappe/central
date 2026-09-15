# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CentralSigningKey(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		kid: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		private_key: DF.Password
		public_key: DF.Code
		published_at: DF.Datetime
	# end: auto-generated types

	pass
