from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date

from central.iam import get_user_team_names
from central.identity.doctype.team.archive import get_archive_checks, get_credit_balances

OPEN_STATUSES = ("Pending Verification", "Pending Approval")


def get_owned_teams(user: str) -> list[dict[str, Any]]:
	"""Unarchived teams `user` owns with their checks; read as the system, since the Team query hides a suspended team."""
	teams = []
	for name in frappe.get_all("Team", {"owner_user": user, "status": ("!=", "Archived")}, pluck="name"):
		team = frappe.get_doc("Team", name)
		teams.append(
			{
				"team": name,
				"team_name": team.team_name,
				"checks": get_deletion_checks(team, user),
				"credit_balances": get_credit_balances(name),
			}
		)
	return teams


def get_deletion_checks(team: Document, user: str) -> list[dict[str, Any]]:
	"""The team's archive checks, plus no other active member and the team not suspended."""
	others = len(
		{member.user for member in team.members if member.user != user and member.status == "Active"}
	)
	return [
		*get_archive_checks(team.name),
		{"key": "members", "passed": others == 0, "count": others},
		{"key": "suspended", "passed": team.status != "Suspended", "count": int(team.status == "Suspended")},
	]


def has_deletion_blockers(user: str) -> bool:
	"""Whether any unarchived team `user` owns fails a check; read as the system, like `get_owned_teams`."""
	return any(
		not check["passed"]
		for name in frappe.get_all("Team", {"owner_user": user, "status": ("!=", "Archived")}, pluck="name")
		for check in get_deletion_checks(frappe.get_doc("Team", name), user)
	)


def get_open_request(user: str) -> dict[str, Any] | None:
	"""The user's deletion request that is still waiting, and when Frappe deletes the account."""
	request = frappe.db.get_value(
		"Personal Data Deletion Request",
		{"email": user, "status": ("in", OPEN_STATUSES)},
		["name", "status", "creation"],
		order_by="creation desc",
		as_dict=True,
	)
	if not request:
		return None

	hours = frappe.db.get_single_value("Website Settings", "auto_account_deletion")
	return {
		"name": request.name,
		"status": request.status,
		"delete_after": add_to_date(request.creation, hours=hours) if hours else None,
	}


def close_memberships(user: str) -> None:
	"""Archive the teams `user` owns and leave the rest, as `user`, so the usual checks apply."""
	previous_user = frappe.session.user
	frappe.set_user(user)
	try:
		for name in get_user_team_names(user):
			team = frappe.get_doc("Team", name)
			if team.owner_user == user:
				team.archive()
			else:
				team.leave()
	finally:
		frappe.set_user(previous_user)


class AccountDeletionRequest:
	"""Central's steps on Frappe's Personal Data Deletion Request."""

	def before_insert(self) -> None:
		if get_open_request(self.email):
			frappe.throw(_("Your account is already set to be deleted."))
		if has_deletion_blockers(self.email):
			frappe.throw(_("Close or hand over the teams you own before you delete your account."))

	@frappe.whitelist()
	def trigger_data_deletion(self) -> None:
		"""Check again and close the user's teams before Frappe redacts; hold the request if not clear."""
		self.validate_data_anonymization()
		if not frappe.db.exists("User", self.email):
			self.put_on_hold()
			self.add_comment("Info", _("On hold: the user no longer exists."))
			return

		if has_deletion_blockers(self.email):
			self.put_on_hold()
			self.add_comment("Info", _("On hold: a team the user owns has open items again."))
			return

		close_memberships(self.email)
		super().trigger_data_deletion()
