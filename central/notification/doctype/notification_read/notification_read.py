import frappe
from frappe.model.document import Document


class NotificationRead(Document):
	pass


def on_doctype_update() -> None:
	_remove_duplicates("Notification Read", ("user", "notification"))
	frappe.db.add_unique("Notification Read", ["user", "notification"])


def _remove_duplicates(doctype: str, identity: tuple[str, ...]) -> None:
	rows = frappe.get_all(doctype, fields=["name", *identity], order_by="creation asc", limit=0)
	seen = set()
	duplicates = []
	for row in rows:
		key = tuple(row.get(field) for field in identity)
		if key in seen:
			duplicates.append(row.name)
		else:
			seen.add(key)
	if duplicates:
		frappe.db.delete(doctype, {"name": ["in", duplicates]})
