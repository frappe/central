# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PlanCategory(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.billing.doctype.plan_category_resource_type.plan_category_resource_type import (
			PlanCategoryResourceType,
		)

		allowed_resource_types: DF.Table[PlanCategoryResourceType]
		billing_interval: DF.Literal["", "Hourly", "Daily", "Monthly"]
		billing_type: DF.Literal["Fixed", "Metered"]
		category_name: DF.Data
		configurator_builder: DF.Literal["VM Rungs", "Simple"]
		description: DF.SmallText | None
		is_active: DF.Check
		pricing_mode: DF.Literal["", "Grandfathered", "Live"]
		provision_target: DF.Literal["", "Server", "Resource"]
		reporting_mode: DF.Literal["", "Authoritative", "Incremental"]
		settlement_mode: DF.Literal["", "Postpaid Overage", "Prepaid Pack"]
		sub_category_label: DF.Data | None
	# end: auto-generated types

	def validate(self):
		# Settlement/reporting mode only govern Metered families; blank them on a Fixed
		# one so the stored shape stays honest (a bundle has no metered reporting).
		if self.billing_type != "Metered":
			self.settlement_mode = None
			self.reporting_mode = None

	def allowed_types(self) -> set[str]:
		"""The resource types a member plan's composition may use. Empty = unconstrained."""
		return {row.resource_type for row in self.allowed_resource_types}

	@property
	def effective_settlement_mode(self) -> str:
		"""Settlement of a Metered family's allowance, blank resolving to the built default
		(ADR 0015). A prepaid pack draws down a purchased balance; postpaid bills overage."""
		return self.settlement_mode or "Postpaid Overage"

	@property
	def effective_reporting_mode(self) -> str:
		"""How this family's usage is reported, blank resolving to the built default
		(ADR 0015). Authoritative replaces the period total; Incremental accumulates deltas."""
		return self.reporting_mode or "Authoritative"

	@property
	def uses_sub_categories(self) -> bool:
		"""A family has a sub-category axis only when it labels one."""
		return bool(self.sub_category_label)
