# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

INVOICED = "Invoiced"
NOTHING_TO_BILL = "Nothing to Bill"
BELOW_MINIMUM = "Below Minimum"
FAILED = "Failed"


class BillingRunTeam(Document):
	pass


def record_outcome(
	team: str, period_end, outcome: str, reason: str | None = None, invoice: str | None = None
) -> None:
	"""Keep what the run last did for this team and month. A retry replaces it."""
	period_end = frappe.utils.getdate(period_end)
	name = frappe.db.exists("Billing Run Team", {"team": team, "period_end": period_end})
	values = {"outcome": outcome, "reason": reason, "invoice": invoice}
	if name:
		frappe.db.set_value("Billing Run Team", name, values)
		return
	# The run writes this record for an operator to read; no user acts here.
	try:
		frappe.get_doc(
			{"doctype": "Billing Run Team", "team": team, "period_end": period_end, **values}
		).insert(ignore_permissions=True, ignore_links=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		pass  # a concurrent worker recorded this team and month first


def has_same_outcome(team: str, period_end, outcome: str, reason: str) -> bool:
	"""Whether a retry met the outcome already on record, so it needs no second log row or event."""
	return bool(
		frappe.db.exists(
			"Billing Run Team",
			{
				"team": team,
				"period_end": frappe.utils.getdate(period_end),
				"outcome": outcome,
				"reason": reason,
			},
		)
	)


def on_doctype_update() -> None:
	frappe.db.add_index("Billing Run Team", ["outcome", "period_end"])
	frappe.db.add_unique("Billing Run Team", ["team", "period_end"], "unique_team_period")
