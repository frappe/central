# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order

# A segment is evidence for a dispute, so after insert only its close is written, and only once.
FIXED_FIELDS = (
	"service",
	"meter",
	"subject",
	"subject_doctype",
	"team",
	"quantity",
	"starts_at",
	"opened_source",
	"opened_by",
	"opened_reference",
)


class UsageSegment(Document):
	def before_insert(self) -> None:
		self.open_key = None if self.ends_at else get_open_key(self.service, self.meter, self.subject)

	def validate(self) -> None:
		if self.is_new():
			self.validate_follows_previous()
		else:
			self.validate_close()
		if self.ends_at and self.is_ending_before_start():
			frappe.throw(_("A Usage Segment cannot end before it starts."))

	def is_ending_before_start(self) -> bool:
		return frappe.utils.get_datetime(self.ends_at) < frappe.utils.get_datetime(self.starts_at)

	def validate_follows_previous(self) -> None:
		"""Refuse a segment that starts while the subject's last segment is still open or before it ended."""
		previous = get_last_segment(self.service, self.meter, self.subject)
		if not previous:
			return
		if not previous.ends_at:
			frappe.throw(_("{0} already has an open Usage Segment {1}.").format(self.subject, previous.name))
		if frappe.utils.get_datetime(self.starts_at) < frappe.utils.get_datetime(previous.ends_at):
			frappe.throw(
				_("A Usage Segment of {0} cannot start before its last one ended at {1}.").format(
					self.subject, previous.ends_at
				)
			)

	def validate_close(self) -> None:
		"""Allow only the close of an open segment: its end and who closed it, written once."""
		before = self.get_doc_before_save()
		changed = [field for field in FIXED_FIELDS if self.has_value_changed(field)]
		if before.ends_at or not self.ends_at or changed:
			frappe.throw(
				_("A Usage Segment can only be closed once. Close it and open a new one to correct it."),
				frappe.PermissionError,
			)
		self.open_key = None

	def on_trash(self) -> None:
		frappe.throw(
			_("A Usage Segment is never deleted. Close it and open a new one to correct it."),
			frappe.PermissionError,
		)


def get_open_key(service: str, meter: str, subject: str) -> str:
	"""The key that allows one open segment per service, meter and subject."""
	return f"{service}|{meter}|{subject}"


def get_last_segment(service: str, meter: str, subject: str, for_update: bool = False) -> frappe._dict | None:
	"""The subject's latest segment of a meter, open or closed, or None."""
	table = frappe.qb.DocType("Usage Segment")
	query = (
		frappe.qb.from_(table)
		.select(table.name, table.quantity, table.starts_at, table.ends_at)
		.where((table.service == service) & (table.meter == meter) & (table.subject == subject))
		.orderby(table.starts_at, order=Order.desc)
		.orderby(table.creation, order=Order.desc)
		.limit(1)
	)
	if for_update:
		query = query.for_update()
	found = query.run(as_dict=True)
	return found[0] if found else None


def on_doctype_update() -> None:
	frappe.db.add_unique("Usage Segment", ["open_key"], constraint_name="unique_open_usage_segment")
	# The writer and the recount read a subject's segments in time order; readiness reads open ones.
	frappe.db.add_index("Usage Segment", ["service", "meter", "subject", "starts_at"])
	frappe.db.add_index("Usage Segment", ["ends_at"])
	frappe.db.add_index("Usage Segment", ["team"])
	# The hourly recount reads the segments opened or closed since its last run.
	frappe.db.add_index("Usage Segment", ["modified"])
