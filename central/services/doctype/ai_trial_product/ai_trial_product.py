# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AITrialProduct(Document):
	"""One product's trial key pool: its size, and the Grove Model Group its keys add to the team's."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		model_group: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pool_size: DF.Int
		product: DF.Link
	# end: auto-generated types
