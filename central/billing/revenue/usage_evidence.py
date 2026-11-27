# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What set a stored usage day and how its service worked the value out, for a dispute."""

import json
from typing import Literal, NotRequired, Required, TypedDict

import frappe
from frappe import _
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Count, GroupConcat, Sum

from central.billing.platform.invariants import Violation
from central.billing.revenue import usage_reports
from central.billing.revenue.usage_month import DAY_FIELDS, bit, slots_of
from central.billing.revenue.usage_month_rows import CORRECTION, DOCTYPE

EVIDENCE = "Evidence"
SEGMENT = "Segment"
MIGRATED = "Migrated"
UNRECORDED = "Unrecorded"
NO_DERIVATION = "None"
MONTH_FIELDS = (
	"name",
	"service",
	"subject",
	"meter",
	"dimension",
	"month",
	"filled",
	"underived",
	"pruned",
	"slots",
)
REPORT_FIELDS = ("name", "service", "kind", "received_at", "as_of", "body_sha256 as sha256")
CORRECTION_FIELDS = ("name", "value", "billed_value", "status", "report", "segment", "derived")
EXAMPLE_SUBJECTS = 5
BitCount = CustomFunction("BIT_COUNT", ["value"])


class Derivation(TypedDict):
	"""How a value was worked out, tagged by kind; None means it arrived without a derivation."""

	kind: Required[Literal["Evidence", "Segment", "Migrated", "Unrecorded", "None"]]
	evidence: NotRequired[dict]
	segment: NotRequired[str]


class ReportEvidence(TypedDict):
	"""A kept report, its body hash, and whether the body is still kept, intact and signed."""

	name: str
	service: str
	kind: str
	received_at: str
	as_of: str | None
	sha256: str
	is_kept: bool
	is_intact: bool
	has_valid_signature: bool


class ValueEvidence(TypedDict):
	"""What set one value. `derived` is the verdict kept on receipt; a value stored before it was kept reads Unrecorded."""

	derived: bool
	report: ReportEvidence | None
	line: dict | None
	derivation: Derivation


class CorrectionEvidence(ValueEvidence):
	"""A later value of a day, with its verdict and derivation read the same way as the day's."""

	value: float
	billed_value: float
	status: str


class DayAnswer(ValueEvidence):
	month_row: str
	day: str
	value: float
	source: str | None
	invoice: str | None
	corrections: list[CorrectionEvidence]


class DayEvidence:
	"""Reads each report body once, and finds in it the line behind a day or a correction."""

	def __init__(self, month: frappe._dict):
		self.month = month
		self.meter = frappe.get_cached_doc("Service", month.service).get_meter(month.meter)
		self.reports: dict[str, ReportEvidence | None] = {}
		self.lines: dict[str, dict[tuple, list[dict]]] = {}

	@classmethod
	def of(cls, month_name: str, day: int) -> DayAnswer:
		"""The value, report, line and derivation behind a day of a month row, and behind each correction of it."""
		return cls(_month(month_name, day)).describe(day)

	def describe(self, day: int) -> DayAnswer:
		"""The day's value and what set it, then each later value kept as a correction."""
		slot = slots_of(self.month.slots).get(str(day), {})
		value = frappe.utils.flt(self.month[DAY_FIELDS[day - 1]])
		derived = not frappe.utils.cint(self.month.underived) & bit(day)
		return {
			"month_row": self.month.name,
			"day": str(self.month.month.replace(day=day)),
			"value": value,
			"source": slot.get("source"),
			"invoice": slot.get("invoice"),
			**self._evidence(derived, slot.get("report"), slot.get("segment"), day, value),
			"corrections": [
				{
					"value": correction.value,
					"billed_value": correction.billed_value,
					"status": correction.status,
					**self._evidence(
						bool(correction.derived), correction.report, correction.segment, day, correction.value
					),
				}
				for correction in _corrections(self.month.name, day)
			],
		}

	def _evidence(self, derived: bool, report: str | None, segment: str | None, day, value) -> ValueEvidence:
		"""The report that set a value, the line in its body, and the derivation recorded for it."""
		kept = self._report(report)
		line = self._line(report, day, value) if kept else None
		return {
			"derived": derived,
			"report": kept,
			"line": line,
			"derivation": _derivation(derived, kept, line, segment),
		}

	def _report(self, name: str | None) -> ReportEvidence | None:
		if not name:
			return None
		if name not in self.reports:
			self.reports[name] = self._read_report(name)
		return self.reports[name]

	def _read_report(self, name: str) -> ReportEvidence | None:
		"""The report's row, whether its body is intact and signed, with the body's lines indexed."""
		report = frappe.db.get_value(usage_reports.DOCTYPE, name, list(REPORT_FIELDS), as_dict=True)
		if not report:
			return None
		body = usage_reports.get_body(name)
		self.lines[name] = _indexed(body)
		is_kept = body is not None
		return {
			**report,
			"is_kept": is_kept,
			"is_intact": is_kept and usage_reports.is_intact(name, body),
			"has_valid_signature": is_kept and usage_reports.has_valid_signature(name, body),
		}

	def _line(self, report: str, day: int, value: float) -> dict | None:
		"""The body's line for the day; of two for the same day, the one whose value the day holds."""
		month = self.month
		key = (month.subject, month.meter, month.dimension or "", str(month.month.replace(day=day)))
		found = self.lines.get(report, {}).get(key, [])
		matching = [line for line in found if self._is_value(line, value)]
		return (matching or found or [None])[-1]

	def _is_value(self, line: dict, value: float) -> bool:
		# Central's own lines keep the stored quantity; a pushed line keeps the service's raw value.
		quantity = line["quantity"] if "quantity" in line else self._quantity_of(line.get("value"))
		return frappe.utils.flt(quantity, 6) == frappe.utils.flt(value, 6)

	def _quantity_of(self, raw) -> float:
		# A meter removed from its Service leaves no divisor, so the raw value is compared as it is.
		return self.meter.quantity_of(raw) if self.meter else frappe.utils.flt(raw)


def _derivation(derived: bool, report: ReportEvidence | None, line: dict | None, segment) -> Derivation:
	"""The recorded derivation of a value, tagged by kind, with the evidence found in its report body."""
	if not derived:
		return {"kind": NO_DERIVATION}
	if segment:
		return {"kind": SEGMENT, "segment": segment}
	if report and report["kind"] == usage_reports.MIGRATED:
		return {"kind": MIGRATED}
	if line and isinstance(line.get("evidence"), dict):
		return {"kind": EVIDENCE, "evidence": line["evidence"]}
	# Derived, yet the kept body shows nothing: stored before the verdict was kept, or the body is gone.
	return {"kind": UNRECORDED}


def check_days_carry_a_derivation(today=None) -> list[Violation]:
	"""Every metered day stored since the start of last month came with how its service worked it out."""
	since = frappe.utils.add_months(frappe.utils.getdate(today).replace(day=1), -1)
	month = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(month)
		.select(
			month.service,
			Count(month.subject).distinct().as_("subjects"),
			Sum(BitCount(month.underived)).as_("days"),
			GroupConcat(month.subject).distinct().as_("names"),
		)
		.where((month.underived > 0) & (month.month >= since) & (month.pruned == 0))
		.groupby(month.service)
	).run(as_dict=True)
	return [_underived_violation(row, since) for row in rows]


def _underived_violation(row: frappe._dict, since) -> Violation:
	examples = ", ".join(sorted(row.names.split(","))[:EXAMPLE_SUBJECTS])
	days = frappe.utils.cint(row.days)
	return Violation(
		check="M8",
		subject_doctype="Service",
		subject=row.service,
		detail=_(
			"{0} day(s) of {1} subject(s) of {2} since {3} came with no derivation, such as {4}. A dispute about them cannot be worked out again until the service sends evidence on each line."
		).format(days, row.subjects, row.service, since.strftime("%B %Y"), examples),
		actual=days,
	)


def _month(name: str, day: int) -> frappe._dict:
	month = frappe.db.get_value(DOCTYPE, name, [*MONTH_FIELDS, *DAY_FIELDS], as_dict=True)
	if not month:
		frappe.throw(_("Usage Month {0} not found.").format(name), frappe.DoesNotExistError)
	if not 1 <= day <= 31 or not frappe.utils.cint(month.filled) & bit(day):
		frappe.throw(_("Day {0} of Usage Month {1} holds no value.").format(day, name))
	if month.pruned:
		frappe.throw(_("Usage Month {0} is past retention, so its days are no longer kept.").format(name))
	return month


def _corrections(month_name: str, day: int) -> list[frappe._dict]:
	return frappe.get_all(
		CORRECTION,
		filters={"parent": month_name, "parenttype": DOCTYPE, "day": day},
		fields=list(CORRECTION_FIELDS),
		order_by="idx asc",
	)


def _indexed(body: bytes | None) -> dict[tuple, list[dict]]:
	"""A body's lines by subject, meter, dimension and day. A body with no lines indexes nothing."""
	report = json.loads(body) if body else {}
	lines = report.get("lines") if isinstance(report, dict) else None
	if not isinstance(lines, list):
		return {}
	index: dict[tuple, list[dict]] = {}
	for line in lines:
		if isinstance(line, dict):
			index.setdefault(_key(line), []).append(line)
	return index


def _key(line: dict) -> tuple:
	return (line.get("subject"), line.get("meter"), line.get("dimension") or "", str(line.get("day")))
