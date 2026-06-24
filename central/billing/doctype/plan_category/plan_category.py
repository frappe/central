# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PlanCategory(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from central.billing.doctype.plan_category_resource_type.plan_category_resource_type import (
			PlanCategoryResourceType,
		)
		from frappe.types import DF

		allowed_resource_types: DF.Table[PlanCategoryResourceType]
		billable_unit: DF.Data | None
		category_name: DF.Data
		configurator_builder: DF.Literal["VM Rungs", "Simple"]
		default_billing_type: DF.Literal["Fixed", "Metered", "Tiered"]
		default_pricing_mode: DF.Literal["Grandfathered", "Live"]
		description: DF.SmallText | None
		is_active: DF.Check
		meter_kind: DF.Literal["None", "Counter", "Gauge"]
		sub_category_label: DF.Data | None
	# end: auto-generated types

	def allowed_types(self) -> set[str]:
		"""The resource types a member plan's composition may use. Empty = unconstrained."""
		return {row.resource_type for row in self.allowed_resource_types}

	@property
	def uses_sub_categories(self) -> bool:
		"""A family has a sub-category axis only when it labels one."""
		return bool(self.sub_category_label)
