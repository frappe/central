from __future__ import annotations

import frappe

# Request values reach whitelisted endpoints as whatever the client sent — a JSON
# body can put a list or a dict where a string is expected. Check the type at the
# trust boundary so a handler never hands a non-scalar to a string operation and
# turns a bad request into an unhandled server error.
#
# Callers pass the whole translated message rather than a field name: a sentence
# assembled from a translated fragment does not survive translation.


def require_text(value, message: str) -> str:
	"""`value` stripped, or `message` as a validation error if it isn't usable text."""
	if not isinstance(value, str) or not value.strip():
		frappe.throw(message, frappe.ValidationError)
	return value.strip()


def require_attached_file(doctype: str, name: str, fieldname: str, file_url) -> str:
	"""`file_url` if it is a File uploaded to that document field, else a validation error."""
	is_attached = isinstance(file_url, str) and frappe.db.exists(
		"File",
		{
			"file_url": file_url,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": fieldname,
		},
	)
	if not is_attached:
		frappe.throw(frappe._("Upload the image again."), frappe.ValidationError)
	return file_url
