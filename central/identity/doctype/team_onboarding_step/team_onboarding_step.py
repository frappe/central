# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TeamOnboardingStep(Document):
	"""One console onboarding step of a team, and what its owner did with it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		status: DF.Literal["Pending", "Done", "Skipped"]
		step: DF.Literal["invite", "billing", "start"]
		updated_by: DF.Link | None
		updated_on: DF.Datetime | None
	# end: auto-generated types
