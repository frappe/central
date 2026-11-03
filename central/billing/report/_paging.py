# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
import frappe
from frappe import _

ROW_LIMIT = 2000


def first_rows(rows: list, message: str | None = None) -> tuple[list, str | None]:
	"""At most ROW_LIMIT rows for the screen, and a note saying how many were left out.

	Work out summaries, charts and columns from every row before calling this. An export
	gets every row."""
	if len(rows) <= ROW_LIMIT or _is_export():
		return rows, message
	note = _("Showing the first {0} of {1} rows. Narrow the filters to see the rest.").format(
		ROW_LIMIT, len(rows)
	)
	return rows[:ROW_LIMIT], f"{message}<br>{note}" if message else note


def _is_export() -> bool:
	return (frappe.form_dict.get("cmd") or "").endswith("export_query")
