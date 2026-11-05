import frappe
from frappe import _
from frappe.model.document import Document


class RunnerLease(Document):
	def validate(self) -> None:
		if frappe.db.get_value("Runner Pool", self.pool, "team") != self.team:
			frappe.throw(_("Runner lease and pool must belong to the same Team."))
		if not self.is_new() and any(
			self.has_value_changed(field) for field in ("team", "pool", "attempt_id", "runner_name")
		):
			frappe.throw(_("Runner lease identity is immutable."))

	def on_trash(self) -> None:
		frappe.throw(_("Runner leases are durable audit records and cannot be deleted."))


def on_doctype_update() -> None:
	frappe.db.add_index("Runner Lease", ["team", "phase"])
	frappe.db.add_index("Runner Lease", ["pool", "phase"])
	frappe.db.add_unique("Runner Lease", ["attempt_id"])
	frappe.db.add_unique("Runner Lease", ["runner_name"])
