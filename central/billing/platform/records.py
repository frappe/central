# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.model.document import Document


def save_billing_record(doc: Document) -> Document:
	"""Save a money record as billing code: mark it for the record guard and skip the
	permission check, because billing runs as the system or on behalf of a team it has
	already authorised."""
	with _billing_write(doc):
		# Billing code writes money records as the system; the record guard checks the mark.
		return doc.save(ignore_permissions=True)


def delete_billing_record(doc: Document, **options) -> None:
	"""Delete a money record as billing code. `options` go to `Document.delete`."""
	with _billing_write(doc):
		# Billing code deletes money records as the system; the record guard checks the mark.
		doc.delete(ignore_permissions=True, **options)


@contextmanager
def _billing_write(doc: Document) -> Iterator[None]:
	"""Mark `doc` for the record guard for one call only, so a later plain save is refused."""
	previous = doc.flags.billing_write
	doc.flags.billing_write = True
	try:
		yield
	finally:
		doc.flags.billing_write = previous


def refuse_manual_edit(doc, method=None) -> None:
	"""1. A new record is allowed; its DocType permissions decide who may create it.
	2. A change that billing code saved through `save_billing_record` is allowed.
	3. Any other change, from Desk or REST and by Administrator too, is refused,
	   also when the caller sets ignore_permissions."""
	if doc.is_new() or doc.flags.billing_write:
		return
	_refuse(doc, _("edited"))


def refuse_manual_delete(doc, method=None) -> None:
	"""1. A delete that billing code made through `delete_billing_record` is allowed.
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
