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


def require_secret(value, message: str) -> str:
	"""Same check for a password, left unstripped — leading and trailing
	whitespace is part of the secret."""
	if not isinstance(value, str) or not value:
		frappe.throw(message, frappe.ValidationError)
	return value
