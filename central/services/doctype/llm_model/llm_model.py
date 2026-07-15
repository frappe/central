# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LLMModel(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		display_name: DF.Data | None
		is_published: DF.Check
		model_key: DF.Data
		tier: DF.Literal["Fast", "Balanced", "Premium"]
	# end: auto-generated types

	_DOCTYPE_NAME = "LLM Model"
