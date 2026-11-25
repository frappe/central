# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document


class GitHubInstallation(Document):
	"""A team's access to one installation of the GitHub App. Server grants and deploy apps go through it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Data | None
		account_type: DF.Literal["User", "Organization"]
		installation_id: DF.Data
		status: DF.Literal["Active", "Disabled"]
		team: DF.Link
	# end: auto-generated types

	@staticmethod
	def link(team: str, installation: dict) -> GitHubInstallation:
		"""The team's row for an installation GitHub listed for the user, created or made active again."""
		name = frappe.db.get_value(
			"GitHub Installation",
			{"team": team, "installation_id": installation["installation_id"]},
			for_update=True,
		)
		doc = frappe.get_doc("GitHub Installation", name) if name else frappe.new_doc("GitHub Installation")
		doc.update(
			{
				"team": team,
				"installation_id": installation["installation_id"],
				"account": installation["account"],
				"account_type": installation["account_type"],
				"status": "Active",
			}
		)
		# Central saves the link after GitHub confirmed the user's access; no Desk user owns it.
		doc.save(ignore_permissions=True)
		return doc

	@staticmethod
	def get_installation_id(name: str) -> str:
		return frappe.db.get_value("GitHub Installation", name, "installation_id")

	@staticmethod
	def is_active(name: str) -> bool:
		return frappe.db.get_value("GitHub Installation", name, "status") == "Active"

	@staticmethod
	def disable_installation(installation_id: str) -> None:
		"""Disable every team's row for an installation that was removed or suspended on GitHub."""
		GitHubInstallation._disable({"installation_id": installation_id, "status": "Active"})

	@staticmethod
	def disable_all() -> None:
		"""Disable every row. Installations of a replaced GitHub App do not work with the new App."""
		GitHubInstallation._disable({"status": "Active"})

	@staticmethod
	def _disable(filters: dict) -> None:
		for name in frappe.get_all("GitHub Installation", filters=filters, pluck="name"):
			doc = frappe.get_doc("GitHub Installation", name, for_update=True)
			doc.status = "Disabled"
			# A GitHub webhook or an App change disables the installation; no Desk user owns it.
			doc.save(ignore_permissions=True)


def on_doctype_update() -> None:
	frappe.db.add_unique("GitHub Installation", ["team", "installation_id"])
	frappe.db.add_index("GitHub Installation", ["installation_id", "status"])
