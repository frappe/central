# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import random_string, today, validate_email_address

from central.central.doctype.central_settings.central_settings import is_connect_url
from central.iam import can
from central.identity.doctype.team_invitation.team_invitation import get_expiry_date
from central.sso import central_url

# The code a customer uses to link with this partner, made the way Frappe Cloud makes a
# partner's referral code (press Team.create_partner_referral_code).
PARTNER_CODE_LENGTH = 10


class PartnerProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		connect_partner_id: DF.Data | None
		expires_on: DF.Date | None
		owner_email: DF.Data | None
		partner_code: DF.Data
		partner_code_hash: DF.Data | None
		partner_name: DF.Data
		return_url: DF.Data | None
		status: DF.Literal["Pending", "Completed", "Expired"]
		team: DF.Link | None
		team_name: DF.Data | None
		token_hash: DF.Data | None
	# end: auto-generated types

	def before_validate(self) -> None:
		if self.owner_email:
			self.owner_email = self.owner_email.strip().lower()
		if not self.partner_name and self.team:
			self.partner_name = frappe.db.get_value("Team", self.team, "team_name")

	def before_insert(self) -> None:
		if not self.partner_code:
			self.partner_code = self._generate_partner_code()
		if self.status == "Pending":
			self.expires_on = get_expiry_date()

	def validate(self) -> None:
		self.partner_code_hash = hash_partner_code(self.partner_code)
		if self.status == "Completed" and not self.team:
			frappe.throw(_("A completed partner needs its team."))
		if self.status == "Pending" and not (self.connect_partner_id and self.owner_email):
			frappe.throw(_("A pending registration needs the Connect partner ID and the owner's email."))
		if self.team:
			self._validate_team()
		if self.return_url and not is_connect_url(self.return_url):
			frappe.throw(_("The return URL must be on the Connect URL in Central Settings."))

	def get_summary(self) -> dict:
		"""What the registration page shows. The emailed link is the key, so whoever holds it
		sees the email it is for."""
		return {
			"partner_name": self.partner_name,
			"email": self.owner_email,
			"status": "Expired" if self.status == "Pending" and not self.is_open() else self.status,
			"has_account": bool(self.owner_email and frappe.db.exists("User", self.owner_email)),
			"expires_on": self.expires_on,
			"connect_url": self.return_url or frappe.db.get_single_value("Central Settings", "connect_url"),
		}

	def complete(self, team: str) -> dict:
		"""The owner picks the team that is the partner. The link works once."""
		user = frappe.session.user
		if user != self.owner_email:
			frappe.throw(_("This registration belongs to another user."), frappe.PermissionError)
		if not self.is_open():
			frappe.throw(
				_("This registration link has expired or was already used. Ask Connect for a new one.")
			)
		if not can(user, team, "billing:manage"):
			frappe.throw(
				_("Only the team's owner or an admin can make it a partner."), frappe.PermissionError
			)

		self.update({"team": team, "status": "Completed", "token_hash": None, "expires_on": None})
		# The owner proved the emailed link and their email. Users hold no Partner Profile permissions.
		self.save(ignore_permissions=True)
		return {"team": self.team, "partner_name": self.partner_name}

	def issue_token(self) -> str:
		"""A new key for the owner's registration link. It replaces the earlier key, so only the
		newest link works. Central keeps only its hash."""
		token, self.token_hash = make_token()
		return token

	def is_open(self) -> bool:
		return self.status == "Pending" and not (self.expires_on and str(self.expires_on) < today())

	def _validate_team(self) -> None:
		other = frappe.db.get_value("Partner Profile", {"team": self.team, "name": ["!=", self.name or ""]})
		if other:
			frappe.throw(_("{0} is already a partner.").format(self.team))
		# A partner's own team can't also be someone's client.
		if frappe.db.exists(
			"Partner Client Link", {"client_team": self.team, "status": ["in", ("Requested", "Active")]}
		):
			frappe.throw(_("{0} works with a partner, so it can't be one.").format(self.team))

	@staticmethod
	def _generate_partner_code() -> str:
		while True:
			code = random_string(PARTNER_CODE_LENGTH).upper()
			if not frappe.db.exists("Partner Profile", {"partner_code": code}):
				return code


def get_registration_by_token(token: str | None) -> PartnerProfile:
	name = frappe.db.get_value("Partner Profile", {"token_hash": hash_token(token)}) if token else None
	if not name:
		frappe.throw(
			_("This registration link is not valid. Ask Connect for a new one."), frappe.DoesNotExistError
		)
	return frappe.get_doc("Partner Profile", name)


def register_connect_partner(
	connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
) -> dict:
	"""Connect's request to know which Central team is one of its partners. The partner's owner
	opens the returned URL, picks the team, and goes back to `return_url` on Connect. A repeated
	call returns the same registration with a new URL, and the earlier URL stops working. A
	completed one returns its team."""
	connect_partner_id, partner_name = connect_partner_id.strip(), partner_name.strip()
	validate_email_address(owner_email, throw=True)
	if not (connect_partner_id and partner_name):
		frappe.throw(_("Send the Connect partner ID and the partner's name."))

	name = frappe.db.get_value("Partner Profile", {"connect_partner_id": connect_partner_id})
	profile = frappe.get_doc("Partner Profile", name) if name else frappe.new_doc("Partner Profile")
	if profile.status == "Completed" and not profile.is_new():
		return {"status": profile.status, "team": profile.team}

	profile.update(
		{
			"connect_partner_id": connect_partner_id,
			"partner_name": partner_name,
			"owner_email": owner_email,
			"return_url": (return_url or "").strip() or None,
			"status": "Pending",
			"expires_on": get_expiry_date(),
		}
	)
	token = profile.issue_token()
	profile.save()
	return {"status": profile.status, "url": f"{central_url()}/dashboard/connect/partner/{token}"}


def get_connect_registration(connect_partner_id: str) -> dict:
	"""Where a Connect partner's registration stands, and its team once completed."""
	row = frappe.db.get_value(
		"Partner Profile",
		{"connect_partner_id": (connect_partner_id or "").strip()},
		["status", "team", "expires_on"],
		as_dict=True,
	)
	if not row:
		return {"status": None, "team": None}
	if row.status == "Pending" and row.expires_on and str(row.expires_on) < today():
		return {"status": "Expired", "team": None}
	return {"status": row.status, "team": row.team if row.status == "Completed" else None}


def get_partner_team_by_link_hash(code_hash: str | None) -> str | None:
	"""The partner team whose code hashes to `code_hash`, or None for a hash no partner has."""
	code_hash = (code_hash or "").strip().lower()
	if len(code_hash) != hashlib.sha256().digest_size * 2:
		return None

	# A system read: Partner Profile holds the codes, so only operators read it directly.
	return frappe.db.get_value(
		"Partner Profile", {"partner_code_hash": code_hash, "status": "Completed"}, "team"
	)


def hash_partner_code(code: str) -> str:
	"""What a link to this partner carries in place of the code, so the customer never sees it.
	A site that sends customers here builds its link with the same hash."""
	return hashlib.sha256(code.strip().encode()).hexdigest()


def make_token() -> tuple[str, str]:
	"""A random key for a one-time link, and the hash Central stores in its place. A leaked
	database row can't be turned back into a working link."""
	token = frappe.generate_hash(length=32)
	return token, hash_token(token)


def hash_token(token: str | None) -> str | None:
	return hashlib.sha256(token.encode()).hexdigest() if token else None


def expire_pending_registrations() -> None:
	for name in frappe.get_all(
		"Partner Profile", filters={"status": "Pending", "expires_on": ["<", today()]}, pluck="name"
	):
		profile = frappe.get_doc("Partner Profile", name)
		profile.status = "Expired"
		profile.save()
