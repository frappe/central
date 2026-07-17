# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LLMPlanPolicy(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.services.doctype.llm_plan_tier.llm_plan_tier import LLMPlanTier

		allowed_tiers: DF.Table[LLMPlanTier]
		plan: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "LLM Plan Policy"
