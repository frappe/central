# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now, today, validate_email_address

from central.iam import get_owned_team_names, is_team_owner
from central.identity.doctype.team.partner import get_partner_team
from central.identity.doctype.team_invitation.team_invitation import get_expiry_date
from central.sso import central_url


class PartnerRegistration(Document):
	"""A request from Frappe Connect for the owner of a partner to choose its Central team."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		completed_on: DF.Datetime | None
		connect_partner_id: DF.Data
		expires_on: DF.Date | None
		owner_email: DF.Data
		partner_name: DF.Data
		return_url: DF.SmallText | None
		status: DF.Literal["Pending", "Completed", "Expired"]
		team: DF.Link | None
		token: DF.Data | None
	# end: auto-generated types

	@classmethod
	def request(
		cls, connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
	) -> dict:
		"""Open a registration for a Connect partner, or return the team it already has.
		A repeated call returns the same URL until the owner email changes or the link expires."""
		team = get_partner_team(connect_partner_id)
		if team:
			return {"status": "Completed", "team": team.name, "partner_code": team.partner_code}

		name = frappe.db.get_value("Partner Registration", {"connect_partner_id": connect_partner_id})
		registration = (
			frappe.get_doc("Partner Registration", name)
			if name
			else frappe.new_doc("Partner Registration", connect_partner_id=connect_partner_id)
		)
		registration.open(partner_name, owner_email, return_url)

		return {"status": "Pending", "url": registration.url}

	@classmethod
	def get_status(cls, connect_partner_id: str) -> dict:
		"""The state Connect reads. It is Completed only while a team holds the partner ID,
		so a team that an operator removed from the program reads as Expired."""
		team = get_partner_team(connect_partner_id)
		if team:
			return {"status": "Completed", "team": team.name, "partner_code": team.partner_code}

		name = frappe.db.get_value("Partner Registration", {"connect_partner_id": connect_partner_id})
		if not name:
			frappe.throw(
				_("No partner registration exists for {0}.").format(connect_partner_id),
				frappe.DoesNotExistError,
			)

		registration = frappe.get_doc("Partner Registration", name)
		return {"status": "Pending" if registration.is_pending else "Expired"}

	def open(self, partner_name: str, owner_email: str, return_url: str | None) -> None:
		owner_email = validate_email_address(owner_email.strip().lower(), throw=True)
		validate_return_url(return_url)

		# A new link for a new owner also cancels the link that the earlier owner got.
		if self.is_new() or not self.is_pending or owner_email != self.owner_email:
			self.token = frappe.generate_hash(length=32)
			self.expires_on = get_expiry_date()

		self.update(
			{
				"partner_name": partner_name,
				"owner_email": owner_email,
				"return_url": return_url or None,
				"status": "Pending",
				"team": None,
				"completed_on": None,
			}
		)
		# The Connect Integration user reaches this record only through central.api.connect.
		self.save(ignore_permissions=True)

	def get_summary(self) -> dict:
		"""What the registration page shows. The owner also gets the teams they can choose."""
		summary = {
			"partner_name": self.partner_name,
			"owner_email": self.owner_email,
			"status": "Expired" if self.status == "Pending" and not self.is_pending else self.status,
			"has_account": bool(frappe.db.exists("User", self.owner_email)),
			"teams": [],
		}
		if frappe.session.user == self.owner_email:
			summary["teams"] = get_registrable_teams(self.owner_email)

		return summary

	# Internal; the HTTP surface is central.api.partners.complete_partner_registration.
	def complete(self, team: str) -> dict:
		"""Make `team` the partner's team.

		1. The signed-in user must be the owner email of the registration.
		2. The registration must be Pending and not expired.
		3. The user must own the team, and the team must be Active.
		4. The team must not already represent a partner."""
		if self.status == "Completed" and self.team == team:
			return self._get_completion()

		self._validate_completion(frappe.session.user, team)

		team_doc = frappe.get_doc("Team", team)
		team_doc.connect_partner_id = self.connect_partner_id
		# connect_partner_id is permlevel 1. A completed registration is the only non-operator path that sets it.
		team_doc.flags.ignore_permlevel_for_fields = ["connect_partner_id"]
		team_doc.save()

		self.update({"status": "Completed", "team": team, "completed_on": now()})
		# The owner proved their email and team above, and has no DocType access to this record.
		self.save(ignore_permissions=True)

		return self._get_completion()

	def _validate_completion(self, user: str, team: str) -> None:
		if user != self.owner_email:
			frappe.throw(
				_("This link is for {0}. Sign in with that email to continue.").format(self.owner_email),
				frappe.PermissionError,
			)
		if not self.is_pending:
			frappe.throw(_("This link has expired. Open the latest link from Frappe Connect."))
		if not is_team_owner(user, team):
			frappe.throw(_("Choose a team that you own."), frappe.PermissionError)
		if frappe.db.get_value("Team", team, "connect_partner_id"):
			frappe.throw(_("This team already represents a partner. Choose another team."))

	def _get_completion(self) -> dict:
		return {"team": self.team, "return_url": self.return_url}

	@property
	def url(self) -> str:
		return f"{central_url()}/dashboard/partner-registration/{self.token}"

	@property
	def is_pending(self) -> bool:
		return self.status == "Pending" and not (
			self.expires_on and getdate(self.expires_on) < getdate(today())
		)


def get_registrable_teams(user: str) -> list[dict]:
	"""The Active teams that `user` owns and that do not represent a partner yet."""
	owned = get_owned_team_names(user)
	if not owned:
		return []

	return frappe.get_all(
		"Team",
		filters={"name": ("in", owned), "connect_partner_id": ("is", "not set")},
		fields=["name", "team_name"],
		order_by="team_name",
	)


def validate_return_url(return_url: str | None) -> None:
	"""A return URL must be on the Connect host, so the registration page cannot be an open redirect."""
	if not return_url:
		return

	connect_url = frappe.db.get_single_value("Central Settings", "connect_url")
	if not connect_url:
		frappe.throw(_("Set the Connect URL in Central Settings before Connect sends a return URL."))

	parsed = urlparse(return_url)
	if parsed.scheme not in ("http", "https") or parsed.hostname != urlparse(connect_url).hostname:
		frappe.throw(
			_("The return URL must be on the Connect host {0}.").format(urlparse(connect_url).hostname)
		)


def get_registration_by_token(token: str) -> PartnerRegistration:
	name = frappe.db.get_value("Partner Registration", {"token": token}) if token else None
	if not name:
		frappe.throw(
			_("This registration link is not valid. Open the latest link from Frappe Connect."),
			frappe.DoesNotExistError,
		)

	return frappe.get_doc("Partner Registration", name)


def expire_pending_registrations() -> None:
	for name in frappe.get_all(
		"Partner Registration",
		filters={"status": "Pending", "expires_on": ["<", today()]},
		pluck="name",
	):
		frappe.db.set_value("Partner Registration", name, "status", "Expired")
