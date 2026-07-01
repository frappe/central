# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PlanSubCategory(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		category: DF.Link
		disk_max: DF.Int
		disk_min: DF.Int
		is_active: DF.Check
		memory_ratio: DF.Literal["", "1:2", "1:4", "1:6", "1:8"]
		ram_ratio: DF.Int
		sub_category_name: DF.Data
		vcpu_steps: DF.Data
	# end: auto-generated types

	pass
