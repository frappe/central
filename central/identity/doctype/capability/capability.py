# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class Capability(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		capability: DF.Data
		description: DF.SmallText | None
		plane: DF.Literal["central", "atlas"]
		resource: DF.Data
	# end: auto-generated types

	pass
