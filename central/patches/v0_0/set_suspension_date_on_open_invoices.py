import frappe
from frappe.query_builder import DocType

from central.billing.doctype.invoice.invoice import owed_filters

OLD_SUSPEND_AFTER_DAYS = 14


def execute() -> None:
	"""Give every open invoice a suspension date: the date the old ladder suspends it.

	The old ladder suspended a team `suspend_after_days` after the invoice's dunning start,
	else its due date. Keeping that date means the new ladder suspends nobody earlier.
	`OLD_SUSPEND_AFTER_DAYS` is the default of the removed `suspend_after_days` field, which an
	unsaved Single used.
	"""
	suspend_after = _old_suspend_after_days()
	invoices = frappe.get_all(
		"Invoice",
		filters=[*owed_filters(), ["suspends_on", "is", "not set"]],
		fields=["name", "due_date", "dunning_starts_on"],
	)
	for invoice in invoices:
		clock_start = invoice.dunning_starts_on or invoice.due_date
		# An Invoice refuses a manual edit through save, so the date is written directly.
		frappe.db.set_value(
			"Invoice",
			invoice.name,
			"suspends_on",
			frappe.utils.add_days(clock_start, suspend_after),
			update_modified=False,
		)


def _old_suspend_after_days() -> int:
	"""The stored `suspend_after_days`. The field left the DocType, so it is read from Singles."""
	singles = DocType("Singles")
	stored = (
		frappe.qb.from_(singles)
		.select(singles.value)
		.where(singles.doctype == "Billing Settings")
		.where(singles.field == "suspend_after_days")
		.run(pluck=True)
	)
	return frappe.utils.cint(stored[0]) if stored and stored[0] else OLD_SUSPEND_AFTER_DAYS
