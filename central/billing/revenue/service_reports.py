# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import base64
import datetime
import hashlib
import hmac
from typing import NoReturn

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

from central.billing.revenue.usage_ledger import utc_today, write_days

MAXIMUM_LINES = 1000
CLOCK_SKEW = datetime.timedelta(minutes=5)


def accept_report(service_name: str | None, signature: str | None, raw_body: bytes) -> dict:
	"""Store a signed report's lines as Usage Days. Only a failed signature refuses the whole call.

	Each line is one subject's value for one UTC day so far, so a report sent again, late or out
	of order changes nothing it should not.
	"""
	service = verified_service(service_name, signature, raw_body)
	report = _parsed(raw_body)
	as_of = reported_at(report.get("as_of"))
	subjects = _subjects(service.name, report["lines"])

	rows, rejected = [], []
	for line in report["lines"]:
		reason = line_problem(service, line, subjects)
		if reason:
			rejected.append(
				{"subject": line.get("subject") if isinstance(line, dict) else None, "reason": reason}
			)
		else:
			rows.append(_row(service, line, subjects[line["subject"]], as_of))
	write_days(rows)
	return {"accepted": len(rows), "rejected": rejected}


def verified_service(service_name: str | None, signature: str | None, raw_body: bytes):
	"""The enabled service whose secret signed this body. The header only picks the secret."""
	if not service_name or not signature:
		_reject("missing service or signature header")
	if not frappe.db.get_value("Service", service_name, "enabled"):
		_reject(f"unknown or disabled service '{service_name}'")

	secret = get_decrypted_password("Service", service_name, "report_secret", raise_exception=False)
	if not secret:
		_reject(f"no report secret for service '{service_name}'")
	expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest())
	# Bytes, not str: compare_digest raises TypeError on a non-ASCII string.
	if not hmac.compare_digest(expected, signature.encode()):
		_reject(f"signature mismatch for service '{service_name}'")

	return frappe.get_doc("Service", service_name)


def reported_at(value) -> datetime.datetime:
	"""A UTC wire time as Central's naive local time. A time with no zone is refused."""
	if not isinstance(value, str) or not value.endswith("Z"):
		frappe.throw(_("as_of must be a UTC time ending in Z."))
	try:
		moment = datetime.datetime.fromisoformat(value.removesuffix("Z")).replace(tzinfo=datetime.UTC)
	except ValueError:
		frappe.throw(_("as_of must be a UTC time ending in Z."))

	moment = frappe.utils.convert_utc_to_system_timezone(moment).replace(tzinfo=None)
	# A reading from the future would bill usage that has not happened.
	if moment > frappe.utils.now_datetime() + CLOCK_SKEW:
		frappe.throw(_("as_of is in the future."))
	return moment


def line_problem(service, line, subjects: dict) -> str | None:
	"""Why a line cannot be stored, or None."""
	if not isinstance(line, dict):
		return _("a line is an object")
	if not service.get_meter(line.get("meter")):
		return _("unknown meter")
	if line.get("subject") not in subjects:
		return _("unknown subject")
	value = line.get("value")
	if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
		return _("value must be a number of at least 0")
	return _day_problem(line.get("day"))


def _day_problem(value) -> str | None:
	try:
		day = datetime.date.fromisoformat(value)
	except (TypeError, ValueError):
		return _("day must be a UTC date like 2026-11-17")
	if day > utc_today():
		return _("day is in the future")
	return None


def _subjects(service_name: str, lines: list) -> dict:
	"""The billed Team Service of each subject in the report, in one query. A service can
	report only for subjects a team turned it on for."""
	names = {line.get("subject") for line in lines if isinstance(line, dict)}
	rows = frappe.get_all(
		"Team Service",
		filters={
			"add_on_service": service_name,
			"external_id": ["in", [name for name in names if isinstance(name, str)]],
			"subscription": ["is", "set"],
		},
		fields=["external_id", "team", "subscription"],
	)
	return {row.external_id: row for row in rows}


def _row(service, line: dict, owner, as_of: datetime.datetime) -> dict:
	meter = service.get_meter(line["meter"])
	return {
		"service": service.name,
		"meter": meter.meter_key,
		"subject": line["subject"],
		"day": line["day"],
		"aggregation": meter.aggregation,
		"team": owner.team,
		"subscription": owner.subscription,
		"resource_type": meter.resource_type,
		"quantity": line["value"] / frappe.utils.flt(meter.unit_divisor),
		"unit": meter.unit,
		"source_amount": line.get("amount"),
		"source_currency": line.get("currency"),
		"as_of": as_of,
	}


def _parsed(raw_body: bytes) -> dict:
	try:
		report = frappe.parse_json(raw_body.decode() or "{}")
	except (UnicodeDecodeError, ValueError):
		report = None
	if not isinstance(report, dict) or not isinstance(report.get("lines"), list):
		frappe.throw(_("A report is an object with a list of lines."))
	if len(report["lines"]) > MAXIMUM_LINES:
		frappe.throw(_("Send at most {0} lines a call.").format(MAXIMUM_LINES))
	return report


def _reject(reason: str) -> NoReturn:
	"""Log which check failed at most once per caller per window; answer everyone the same."""
	logged_key = f"service-report:rejected:{frappe.local.request_ip}"
	if not frappe.cache.get_value(logged_key):
		frappe.log_error(title="Rejected usage report", message=reason[:200])
		frappe.cache.set_value(logged_key, 1, expires_in_sec=10 * 60)

	frappe.throw(_("Invalid signature."), frappe.PermissionError)
