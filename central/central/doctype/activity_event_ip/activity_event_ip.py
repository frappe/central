import frappe
from frappe.model.document import Document


class ActivityEventIP(Document):
	"""The request address of one activity row, kept off the customer-readable table."""

	def on_doctype_update(self) -> None:
		frappe.db.add_index("Activity Event IP", ["team", "occurred_at"])
