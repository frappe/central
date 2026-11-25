# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
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
		status: DF.Literal["Active", "Suspended", "Disabled"]
		team: DF.Link
	# end: auto-generated types

	def on_update(self) -> None:
		if not self.has_value_changed("status") or self.status == "Active":
			return

		from central.deploy.doctype.deploy_app.deploy_app import DeployApp
		from central.infrastructure.doctype.github_connection.github_connection import GitHubConnection

		GitHubConnection.disable_for_installation(self.name)
		if self.status == "Disabled":
			# We don't care about suspension here
			DeployApp.disable_for_installation(self.name)

	@staticmethod
	def link(team: str, installation: dict) -> GitHubInstallation:
		"""The team's row for an installation GitHub listed for the user, created or made active again."""
		if installation.get("is_suspended"):
			frappe.throw(
				_("The GitHub App is suspended on {0}. An owner of {0} must unsuspend it first.").format(
					installation["account"]
				),
				frappe.PermissionError,
			)

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
		"""Disable every team's row for an installation that was removed on GitHub."""
		GitHubInstallation._set_status(
			{"installation_id": installation_id, "status": ["!=", "Disabled"]}, "Disabled"
		)

	@staticmethod
	def suspend_installation(installation_id: str) -> None:
		GitHubInstallation._set_status({"installation_id": installation_id, "status": "Active"}, "Suspended")

	@staticmethod
	def unsuspend_installation(installation_id: str) -> None:
		GitHubInstallation._set_status({"installation_id": installation_id, "status": "Suspended"}, "Active")

	@staticmethod
	def disable_all() -> None:
		"""Disable every row. Installations of a replaced GitHub App do not work with the new App."""
		GitHubInstallation._set_status({"status": ["!=", "Disabled"]}, "Disabled")

	@staticmethod
	def _set_status(filters: dict, status: str) -> None:
		for name in frappe.get_all("GitHub Installation", filters=filters, pluck="name"):
			doc = frappe.get_doc("GitHub Installation", name, for_update=True)
			doc.status = status
			# A GitHub webhook or an App change sets the status; no Desk user owns it.
			doc.save(ignore_permissions=True)


def on_doctype_update() -> None:
	frappe.db.add_unique("GitHub Installation", ["team", "installation_id"])
	frappe.db.add_index("GitHub Installation", ["installation_id", "status"])
