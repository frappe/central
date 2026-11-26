# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A document's PDF from the accounting system: rendered the first time someone asks for it,
then kept as a private file on the Central record and served from there.

The accounting system is slow to render a PDF, so nothing is fetched before a download.
"""

from collections.abc import Callable

import frappe

# The Central record, the field that keeps its PDF's file URL.
PDF_FIELDS = {"Invoice": "pdf_url", "Credit Ledger Entry": "receipt_url"}


def stored_pdf(doctype: str, name: str, filename: str, render: Callable[[], bytes]) -> bytes:
	"""The record's PDF: the kept file, else `render()`, which is then kept."""
	if content := _read(frappe.db.get_value(doctype, name, PDF_FIELDS[doctype])):
		return content
	content = render()
	_keep(doctype, name, filename, content)
	return content


def forget_pdf(doctype: str, name: str) -> None:
	"""Drop the kept PDF, so the next download renders it again, for example after a print format change."""
	field = PDF_FIELDS[doctype]
	url = frappe.db.get_value(doctype, name, field)
	for file in frappe.get_all("File", filters={"file_url": url, "attached_to_name": name}, pluck="name"):
		# Central's own copy of the PDF, which no user owns.
		frappe.delete_doc("File", file, ignore_permissions=True)
	frappe.db.set_value(doctype, name, field, None, update_modified=False)


def _read(url: str | None) -> bytes | None:
	file = url and frappe.db.get_value("File", {"file_url": url}, "name")
	return frappe.get_doc("File", file).get_content() if file else None


def _keep(doctype: str, name: str, filename: str, content: bytes) -> None:
	field = PDF_FIELDS[doctype]
	if frappe.db.get_value(doctype, name, field, for_update=True):
		return  # another download kept it first
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"is_private": 1,
			"content": content,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": field,
		}
	)
	# A member may download the invoice but not attach files to it; the file is Central's copy.
	file.insert(ignore_permissions=True)
	frappe.db.set_value(doctype, name, field, file.file_url, update_modified=False)
	frappe.local.flags.commit = True  # a GET request commits only when it asks to
