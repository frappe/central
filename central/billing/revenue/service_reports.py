# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import base64
import datetime
import hashlib
import hmac
from typing import NoReturn

import frappe
from frappe import _

from central.billing.revenue.report_subjects import subjects_by_day
from central.billing.revenue.usage_ledger import utc_today, write_days
from central.services.doctype.service.service import get_report_secret

MAXIMUM_LINES = 1000
# Far above any one subject's daily value in raw units, and low enough to divide safely.
MAXIMUM_VALUE = 10**18
MAXIMUM_CURRENCY = 10
MAXIMUM_DIMENSION = 140
CLOCK_SKEW = datetime.timedelta(minutes=5)


def accept_report(service_name: str | None, signature: str | None, raw_body: bytes) -> dict:
	"""Store a signed report's lines as Usage Days. Only a failed signature refuses the whole call."""
	# Each line is one subject's value for one UTC day so far, so a resent, late or reordered report
	# changes nothing it should not.
	service = verified_service(service_name, signature, raw_body)
	report = _parsed(raw_body)
	as_of = reported_at(report.get("as_of"))
	if _is_read_by_central_locked(service.name):
		# Central's own reading still bills this service, so a pushed day would bill its usage twice.
		reason = _("Central still reads this service; send it again after the switch")
		answer = {"accepted": 0, "rejected": [_refused(line, reason, retry=True) for line in report["lines"]]}
	else:
		answer = _stored(service, report["lines"], as_of)
	_record_report(service.name, as_of)
	return answer


def _is_read_by_central_locked(service_name: str) -> bool:
	"""Whether Central reads the service itself, read under the Service row lock."""
	# Held until the report commits, so an operator switching Central's reads on waits for this
	# report, and no pushed day is stored once the switch has saved.
	return bool(frappe.db.get_value("Service", service_name, "central_reads", for_update=True))


def _stored(service, lines: list, as_of: datetime.datetime) -> dict:
	"""Write each valid line as a Usage Day and name every line that was not stored."""
	# A server's backup bucket bills only on the days its server billed, so subjects are per day.
	subjects = subjects_by_day(service.name, _subject_names(lines), _days(lines))

	rows, rejected = [], []
	for line in lines:
		day_subjects = subjects.get(_day_of(line), {})
		problem = line_problem(service, line, day_subjects)
		if problem:
			reason, retry = problem
			rejected.append(_refused(line, reason, retry=retry))
		else:
			rows.append(_row(service, line, day_subjects[line["subject"]], as_of))
	conflicts = write_days(rows).conflicts
	# A day another worker wrote at the same moment is not confirmed, so the service sends it again.
	rejected += [
		_refused(row, _("the day changed at the same time; send it again"), retry=True) for row in conflicts
	]
	return {"accepted": len(rows) - len(conflicts), "rejected": rejected}


def _record_report(service_name: str, as_of: datetime.datetime) -> None:
	# Any signed report shows the service is alive, even one whose every line is refused.
	frappe.db.set_value(
		"Service",
		service_name,
		{"last_report_at": frappe.utils.now_datetime(), "last_report_as_of": as_of},
		update_modified=False,
	)


def _refused(line, reason: str, retry: bool) -> dict:
	"""A refused line, named so the service can find it in its outbox; `retry` says whether to resend."""
	values = line if isinstance(line, dict) else {}
	named = {key: _text(values.get(key)) for key in ("subject", "meter", "day")}
	# The ledger keeps a line with no dimension as "", so every refusal names it that way.
	return {**named, "dimension": _text(values.get("dimension")) or "", "reason": reason, "retry": retry}


def _text(value) -> str | None:
	# A malformed line can carry any JSON here; only plain values are echoed back.
	if isinstance(value, datetime.date):
		return value.isoformat()
	return value if isinstance(value, str) else None


def verified_service(service_name: str | None, signature: str | None, raw_body: bytes):
	"""The enabled service whose secret signed this body. The header only picks the secret."""
	if not service_name or not signature:
		_reject("missing service or signature header")
	if not frappe.db.get_value("Service", service_name, "enabled"):
		_reject(f"unknown or disabled service '{service_name}'")

	secret = get_report_secret(service_name)
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


def line_problem(service, line, subjects: dict) -> tuple[str, bool] | None:
	"""Why a line cannot be stored and whether sending it again later can help, or None."""
	malformed = _format_problem(service, line)
	if malformed:
		return malformed, False
	# Both can clear later: a team may subscribe after it used the service, and a service's clock
	# may run a little ahead of Central's.
	if _subject_of(line) not in subjects:
		return _("unknown subject"), True
	if datetime.date.fromisoformat(line["day"]) > utc_today():
		return _("day is in the future"), True
	return None


def _format_problem(service, line) -> str | None:
	if not isinstance(line, dict):
		return _("a line is an object")
	if not isinstance(line.get("meter"), str) or not service.get_meter(line["meter"]):
		return _("unknown meter")
	if _subject_of(line) is None:
		return _("subject must be text")
	return (
		_value_problem(service, line)
		or _dimension_problem(line.get("dimension"))
		or _source_problem(line)
		or _day_problem(line.get("day"))
	)


def _value_problem(service, line: dict) -> str | None:
	# A meter that counts corrections, such as AI cost, may go below zero.
	lowest = -MAXIMUM_VALUE if service.get_meter(line["meter"]).allow_negative else 0
	if _is_number_in_range(line.get("value"), lowest):
		return None
	return _("value must be a number from {0} to {1}").format(lowest, MAXIMUM_VALUE)


def _dimension_problem(dimension) -> str | None:
	if dimension is None or (isinstance(dimension, str) and len(dimension) <= MAXIMUM_DIMENSION):
		return None
	return _("dimension must be text of at most {0} characters").format(MAXIMUM_DIMENSION)


def _is_number_in_range(value, lowest: float) -> bool:
	# NaN and infinity fail the range check too.
	if isinstance(value, bool) or not isinstance(value, int | float):
		return False
	return lowest <= value <= MAXIMUM_VALUE


def _source_problem(line: dict) -> str | None:
	amount, currency = line.get("amount"), line.get("currency")
	if amount is not None and not _is_number_in_range(amount, -MAXIMUM_VALUE):
		return _("amount must be a number")
	if currency is not None and not (isinstance(currency, str) and 0 < len(currency) <= MAXIMUM_CURRENCY):
		return _("currency must be a currency code")
	return None


def _day_problem(value) -> str | None:
	try:
		datetime.date.fromisoformat(value)
	except (TypeError, ValueError):
		return _("day must be a UTC date like 2026-11-17")
	return None


def _subject_of(line) -> str | None:
	subject = line.get("subject") if isinstance(line, dict) else None
	return subject if isinstance(subject, str) else None


def _subject_names(lines: list) -> list[str]:
	return list({subject for line in lines if (subject := _subject_of(line))})


def _day_of(line) -> str | None:
	return _text(line.get("day")) if isinstance(line, dict) else None


def _days(lines: list) -> set[str]:
	return {day for line in lines if (day := _day_of(line)) and _day_problem(day) is None}


def _row(service, line: dict, subject, as_of: datetime.datetime) -> dict:
	# A server's backup bucket carries the storage its server's plan included that day.
	bundle = {"included": subject.included} if "included" in subject else {}
	return service.get_meter(line["meter"]).get_day_row(
		subject,
		line["day"],
		line["value"],
		dimension=line.get("dimension"),
		source_amount=line.get("amount"),
		source_currency=line.get("currency"),
		as_of=as_of,
		**bundle,
	)


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
