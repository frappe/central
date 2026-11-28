# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import base64
import gzip
import hashlib
import hmac
import json

import frappe

from central.services.doctype.service.service import get_report_secret

DOCTYPE = "Usage Report"
PUSHED = "Pushed"
READ_BY_CENTRAL = "Read By Central"
ESTIMATED = "Estimated"
MIGRATED = "Migrated"
FINGERPRINT_LENGTH = 12


def record(
	service: str,
	kind: str,
	body: bytes,
	as_of=None,
	signature: str | None = None,
	line_count: int = 0,
	name: str | None = None,
) -> str:
	"""Keep a report and its raw body as evidence, and return the report's name."""
	report = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"service": service,
			"kind": kind,
			"received_at": frappe.utils.now_datetime(),
			"as_of": as_of,
			"line_count": line_count,
			"body_sha256": hashlib.sha256(body).hexdigest(),
			"signature": signature,
			"secret_fingerprint": _fingerprint(service) if signature else None,
		}
	)
	# A signed service call or a scheduled job writes the evidence; neither has a user who may.
	report.insert(ignore_permissions=True, set_name=name)
	_attach_body(report.name, body)
	return report.name


def record_lines(service: str, kind: str, lines: list[dict], name: str | None = None) -> str:
	"""Keep the lines Central read or estimated itself as one report, and return its name."""
	body = central_body(lines)
	return record(service, kind, body, line_count=len(lines), name=name)


def set_counts(name: str, accepted: int, rejected: int) -> None:
	"""Record how many of the report's lines were stored and how many were refused."""
	frappe.db.set_value(
		DOCTYPE, name, {"accepted_count": accepted, "rejected_count": rejected}, update_modified=False
	)


def central_body(lines: list[dict]) -> bytes:
	"""The lines Central wrote itself, as canonical JSON, so their hash is stable."""
	return canonical_json({"lines": lines})


def canonical_json(payload: dict) -> bytes:
	"""`payload` as JSON with sorted keys and no spaces, so the same content always hashes the same."""
	return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()


def signature_of(secret: str, body: bytes) -> bytes:
	"""The base64 HMAC-SHA256 a service signs its report body with."""
	return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest())


def get_body(name: str) -> bytes | None:
	"""The report's body as it was received, or None when it is no longer kept."""
	url = frappe.db.get_value(DOCTYPE, name, "body")
	file = url and frappe.db.get_value("File", {"file_url": url, "attached_to_name": name}, "name")
	if not file:
		return None
	return gzip.decompress(frappe.get_doc("File", file).get_content())


def is_intact(name: str, body: bytes | None = None) -> bool:
	"""Whether the kept body, or `body` read from it already, still has the hash recorded when it was received."""
	body = get_body(name) if body is None else body
	if body is None:
		return False
	return hmac.compare_digest(
		hashlib.sha256(body).hexdigest(), frappe.db.get_value(DOCTYPE, name, "body_sha256")
	)


def has_valid_signature(name: str, body: bytes | None = None) -> bool:
	"""Whether the kept body, or `body` read from it already, verifies against the signature it came with."""
	report = frappe.db.get_value(DOCTYPE, name, ["service", "signature", "secret_fingerprint"], as_dict=True)
	body = get_body(name) if body is None else body
	if not (report and report.signature and body is not None):
		return False
	# A rotated secret cannot verify a body signed with the old one.
	if report.secret_fingerprint != _fingerprint(report.service):
		return False
	expected = signature_of(get_report_secret(report.service), body)
	return hmac.compare_digest(expected, report.signature.encode())


def _attach_body(name: str, body: bytes) -> None:
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{name}.json.gz",
			"is_private": 1,
			"content": gzip.compress(body),
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": name,
			"attached_to_field": "body",
		}
	)
	# The body is Central's evidence, which no user owns.
	file.insert(ignore_permissions=True)
	frappe.db.set_value(DOCTYPE, name, "body", file.file_url, update_modified=False)


def _fingerprint(service: str) -> str | None:
	secret = get_report_secret(service)
	return hashlib.sha256(secret.encode()).hexdigest()[:FINGERPRINT_LENGTH] if secret else None
