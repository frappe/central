# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def mark_billing_write(doc: Document) -> Document:
	"""Mark a money record as changed by billing code, so its next save or delete is allowed.
	Returns the same document."""
	doc.flags.billing_write = True
	return doc


def refuse_manual_edit(doc, method=None) -> None:
	"""1. A new record is allowed; its DocType permissions decide who may create it.
	2. A change that billing code marked with `mark_billing_write` is allowed.
	3. Any other change, from Desk or REST and by Administrator too, is refused,
	   also when the caller sets ignore_permissions."""
	if doc.is_new() or doc.flags.billing_write:
		return
	_refuse(doc, _("edited"))


def refuse_manual_delete(doc, method=None) -> None:
	"""1. A delete that billing code marked with `mark_billing_write` is allowed.
	2. Any other delete, from Desk or REST and by Administrator too, is refused,
	   also when the caller sets ignore_permissions."""
	if doc.flags.billing_write:
		return
	_refuse(doc, _("deleted"))


def _refuse(doc, what: str) -> None:
	frappe.throw(
		_("{0} {1} is a money record and cannot be {2} by hand. Use its billing action instead.").format(
			_(doc.doctype), doc.name, what
		),
		frappe.PermissionError,
	)
