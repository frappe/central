from __future__ import annotations

from frappe.model.document import Document


class HostTask(Document):
	"""Audit row for one privileged script run on the Central host (the WireGuard
	hub). Written by `central.host_task.run_host_task`; never created by hand —
	there is no operator form action, only the read-only audit list."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		duration_milliseconds: DF.Int
		ended: DF.Datetime | None
		exit_code: DF.Int
		script: DF.Data
		started: DF.Datetime | None
		status: DF.Literal["Pending", "Running", "Success", "Failure"]
		stderr: DF.Code | None
		stdout: DF.Code | None
		triggered_by: DF.Link
		variables: DF.LongText | None
	# end: auto-generated types
	pass
