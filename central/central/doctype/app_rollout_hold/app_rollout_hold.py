# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.database import savepoint
from frappe.model.document import Document

# The length of a Data field.
TEXT_LIMIT = 140


class AppRolloutHold(Document):
	"""A release Pilot must not offer, because too many of its updates failed."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app: DF.Data
		commit: DF.Data
		error: DF.SmallText | None
		failed: DF.Int
		held_at: DF.Datetime | None
		released: DF.Check
		total: DF.Int
	# end: auto-generated types

	@staticmethod
	def get_held_commits() -> list[str]:
		"""Commits Pilot must not offer: every hold a person has not released."""
		return frappe.get_all("App Rollout Hold", filters={"released": 0}, pluck="name")

	@staticmethod
	def hold_failing_releases(rows: object) -> None:
		"""Hold each release that crosses the failure limits in Central Settings. Every row is
		checked before any is held, so a wrong alert setup fails the whole run instead of
		holding half of it."""
		if not isinstance(rows, list):
			frappe.throw(_("An app rollout alert must send its rows as a list."))

		holds = [AppRolloutHold._get_hold(row) for row in rows]
		settings = frappe.get_cached_doc("Central Settings")
		for hold in holds:
			if hold["total"] < settings.app_rollout_minimum_servers:
				continue

			failure_percent = hold["failed"] * 100 / hold["total"]
			if failure_percent <= settings.app_rollout_failure_percent:
				continue

			# The commit is the name, so a release already held, or released, keeps its row.
			with savepoint(catch=frappe.DuplicateEntryError):
				frappe.new_doc("App Rollout Hold").update(hold).insert()

	@staticmethod
	def _get_hold(row: object) -> dict:
		if not isinstance(row, dict):
			frappe.throw(_("An app rollout alert row must be an object, not {0}.").format(row))

		for key in ("app", "to_commit"):
			value = row.get(key)
			if not isinstance(value, str) or not 1 <= len(value) <= TEXT_LIMIT:
				frappe.throw(_("An app rollout alert row needs {0} as text: {1}").format(key, row))

		failed = row.get("failed")
		total = row.get("total")
		for value in (failed, total):
			if isinstance(value, bool) or not isinstance(value, int):
				frappe.throw(_("An app rollout alert row needs failed and total as numbers: {0}").format(row))

		if total < 1 or not 0 <= failed <= total:
			frappe.throw(
				_(
					"An app rollout alert row needs a total of at least 1, and failed between 0 and total: {0}"
				).format(row)
			)

		if "error" not in row or not isinstance(row["error"], str | None):
			frappe.throw(_("An app rollout alert row needs error as text: {0}").format(row))

		return {
			"app": row["app"],
			"commit": row["to_commit"],
			"failed": failed,
			"total": total,
			"error": row["error"] or "",
			"held_at": frappe.utils.now_datetime(),
		}


def on_doctype_update() -> None:
	frappe.db.add_index("App Rollout Hold", ["released"])
