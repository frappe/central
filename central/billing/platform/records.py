# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def refuse_manual_edit(doc, method=None) -> None:
	"""1. A new record is allowed; its DocType permissions decide who may create it.
	2. A change made by billing code (ignore_permissions) is allowed.
	3. Any other change, from Desk or REST and by Administrator too, is refused."""
	if doc.is_new() or doc.flags.ignore_permissions:
		return
	_refuse(doc, _("edited"))


def refuse_manual_delete(doc, method=None) -> None:
	"""1. A delete made by billing code (ignore_permissions) is allowed.
	2. Any other delete, from Desk or REST and by Administrator too, is refused."""
	if doc.flags.ignore_permissions:
		return
	_refuse(doc, _("deleted"))


def _refuse(doc, what: str) -> None:
	frappe.throw(
		_("{0} {1} is a money record and cannot be {2} by hand. Use its billing action instead.").format(
			_(doc.doctype), doc.name, what
		),
		frappe.PermissionError,
	)
