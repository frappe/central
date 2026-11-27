# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What set a stored usage day and how its service worked the value out, for a dispute."""

import json

import frappe
from frappe import _
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Count, GroupConcat, Sum

from central.billing.platform.invariants import Violation
from central.billing.revenue import usage_reports
from central.billing.revenue.service_reports import evidence_of
from central.billing.revenue.usage_month import DAY_FIELDS, bit, slots_of
from central.billing.revenue.usage_month_rows import CORRECTION, DOCTYPE

NO_DERIVATION = "none"
MONTH_FIELDS = ("name", "service", "subject", "meter", "dimension", "month", "filled", "pruned", "slots")
REPORT_FIELDS = ("name", "service", "kind", "received_at", "as_of", "body_sha256")
CORRECTION_FIELDS = ("name", "value", "billed_value", "status", "report", "segment")
EXAMPLE_SUBJECTS = 5
BitCount = CustomFunction("BIT_COUNT", ["value"])


class DayEvidence:
	"""Reads each report body once, and finds in it the line behind a day or a correction."""

	def __init__(self, month: frappe._dict):
		self.month = month
		self.service = frappe.get_cached_doc("Service", month.service)
		meter = self.service.get_meter(month.meter)
		self.divisor = frappe.utils.flt(meter.unit_divisor) if meter else 1
		self.reports: dict[str, dict | None] = {}
		self.lines: dict[str, dict[tuple, list[dict]]] = {}

	@classmethod
	def of(cls, month_name: str, day: int) -> dict:
		"""The value, report, line and derivation behind a day of a month row, and behind each correction of it."""
		return cls(_month(month_name, day)).describe(day)

	def describe(self, day: int) -> dict:
		"""The day's value and what set it, then each later value kept as a correction."""
		slot = slots_of(self.month.slots).get(str(day), {})
		value = frappe.utils.flt(self.month[DAY_FIELDS[day - 1]])
		return {
			"month_row": self.month.name,
			"day": str(self.month.month.replace(day=day)),
			"value": value,
			"source": slot.get("source"),
			"invoice": slot.get("invoice"),
			**self._evidence(slot.get("report"), slot.get("segment"), day, value),
			"corrections": [
				{
					"value": correction.value,
					"billed_value": correction.billed_value,
					"status": correction.status,
					**self._evidence(correction.report, correction.segment, day, correction.value),
				}
				for correction in _corrections(self.month.name, day)
			],
		}

	def _evidence(self, report: str | None, segment: str | None, day: int, value: float) -> dict:
		"""The report that set a value, the line in its body, and the derivation that line carries."""
		kept = self._report(report)
		line = self._line(report, day, value) if kept else None
		return {"report": kept, "line": line, "derivation": self._derivation(kept, line, segment)}

	def _report(self, name: str | None) -> dict | None:
		if not name:
			return None
		if name not in self.reports:
			self.reports[name] = self._read_report(name)
		return self.reports[name]

	def _read_report(self, name: str) -> dict | None:
		"""The report's row, whether its body is intact and signed, with the body's lines indexed."""
		report = frappe.db.get_value(usage_reports.DOCTYPE, name, list(REPORT_FIELDS), as_dict=True)
		if not report:
			return None
		body = usage_reports.get_body(name)
		self.lines[name] = _indexed(body)
		is_kept = body is not None
		return {
			**report,
			"sha256": report.pop("body_sha256"),
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
		quantity = (
			line["quantity"] if "quantity" in line else frappe.utils.flt(line.get("value")) / self.divisor
		)
		return frappe.utils.flt(quantity, 6) == frappe.utils.flt(value, 6)

	def _derivation(self, report: dict | None, line: dict | None, segment: str | None) -> dict | str:
		if line and self._is_derivation(report, line):
			return line["evidence"]
		if segment:
			return {"segment": segment}
		return NO_DERIVATION

	def _is_derivation(self, report: dict, line: dict) -> bool:
		# A pushed line's evidence counts only when it passed the checks it was stored under.
		if report["kind"] == usage_reports.PUSHED:
			return evidence_of(self.service, line) is not None
		return isinstance(line.get("evidence"), dict)


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
