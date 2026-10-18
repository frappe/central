# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now, today, validate_email_address

from central.central.doctype.central_settings.central_settings import is_connect_url
from central.central.doctype.partner_profile.partner_profile import hash_token, make_token
from central.iam import can
from central.identity.doctype.team_invitation.team_invitation import get_expiry_date
from central.sso import central_url

# A link in either of these states still holds the client team.
ACTIVE_STATUSES = ("Requested", "Active")
FINAL_STATUSES = ("Declined", "Expired", "Ended")

# The states each state can move to. A final state never changes, so a new period of work
# with the same partner gets a new link.
NEXT_STATUSES = {
	"Requested": ("Active", "Declined", "Expired", "Ended"),
	"Active": ("Ended",),
}

CONNECT_FIELDS = ("source_reference", "customer_email", "project_title", "return_url")


class PartnerClientLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		buffer: DF.Currency
		client_team: DF.Link | None
		client_team_name: DF.Data | None
		customer_email: DF.Data | None
		end_reason: DF.SmallText | None
		ended_by: DF.Link | None
		ended_on: DF.Datetime | None
		expires_on: DF.Date | None
		paid_by_partner: DF.Check
		partner_access: DF.Check
		partner_team: DF.Link
		partner_team_name: DF.Data | None
		project_title: DF.Data | None
		requested_by: DF.Link | None
		return_url: DF.Data | None
		source: DF.Literal["Partner Code", "Connect"]
		source_reference: DF.Data | None
		spend_limit: DF.Currency
		status: DF.Literal["Requested", "Active", "Declined", "Expired", "Ended"]
		token_hash: DF.Data | None
	# end: auto-generated types

	def before_validate(self) -> None:
		if self.customer_email:
			self.customer_email = self.customer_email.strip().lower()

	def before_insert(self) -> None:
		if self.source == "Partner Code" and not self.requested_by and frappe.session.user != "Guest":
			self.requested_by = frappe.session.user
		if self.status == "Requested":
			self.expires_on = get_expiry_date()

	def validate(self) -> None:
		self._validate_status_change()
		self._validate_distinct_teams()
		self._validate_partner_team()
		self._validate_client_team()
		self._validate_single_active_link()
		if self.source == "Connect":
			self._validate_connect_fields()

	def issue_token(self) -> str:
		"""A new key for the customer's setup link. It replaces the earlier key, so only the
		newest link works. Central keeps only its hash."""
		token, self.token_hash = make_token()
		return token

	def is_open(self) -> bool:
		return self.status == "Requested" and not (self.expires_on and str(self.expires_on) < today())

	def get_summary(self) -> dict:
		"""What the customer sees of a Connect request. The emailed link is the key, so whoever
		holds it sees the email it is for."""
		logo = frappe.db.get_value("Team", self.partner_team, "team_logo")
		return {
			"name": self.name,
			"partner_name": self.partner_team_name,
			"logo": logo,
			"project_title": self.project_title,
			"email": self.customer_email,
			"status": "Expired" if self.status == "Requested" and not self.is_open() else self.status,
			"has_account": bool(frappe.db.exists("User", self.customer_email)),
			"expires_on": self.expires_on,
			"return_url": self.return_url,
		}

	def accept(self, team: str, paid_by_partner: bool | int = 0, partner_access: bool | int = 0) -> None:
		"""The customer picks the team the partner works on, and who pays for hosting. A partner
		who pays always gets access; otherwise the customer decides, now or later."""
		self._require_customer()
		if not can(frappe.session.user, team, "billing:manage"):
			frappe.throw(_("Only the account's owner or an admin can add a partner."), frappe.PermissionError)

		self._replace_earlier_links(team)
		self.update(
			{
				"client_team": team,
				"status": "Active",
				"paid_by_partner": cint(paid_by_partner),
				"partner_access": 1 if cint(paid_by_partner) else cint(partner_access),
				"token_hash": None,
			}
		)
		# The customer proved their email. Users never write a link directly (rule 4 of its permissions).
		self.save(ignore_permissions=True)

	def set_partner_access(self, team: str, partner_access: bool | int) -> None:
		"""The customer gives the partner access, or takes it away. The caller has checked
		billing:manage on `team`."""
		if team != self.client_team or self.status != "Active":
			frappe.throw(_("This partner link isn't active on your team."), frappe.PermissionError)
		if self.paid_by_partner and not cint(partner_access):
			frappe.throw(_("A partner who pays for hosting keeps access. Pay for hosting yourself first."))

		self.partner_access = cint(partner_access)
		# As in end_for_team.
		self.save(ignore_permissions=True)

	def _replace_earlier_links(self, team: str) -> None:
		"""A confirmed hire takes over an earlier link between the same partner and team, so the
		team keeps one. A link with another partner still blocks the hire."""
		for name in frappe.get_list(
			"Partner Client Link",
			filters={
				"client_team": team,
				"partner_team": self.partner_team,
				"status": ["in", ACTIVE_STATUSES],
				"name": ["!=", self.name],
			},
			pluck="name",
		):
			earlier = frappe.get_doc("Partner Client Link", name)
			# The customer ends their own earlier link as part of accepting, as in accept.
			earlier.flags.ignore_permissions = True
			earlier.end(_("Replaced by the hire for {0} on Connect.").format(self.project_title))

	def _require_customer(self) -> None:
		if self.source != "Connect" or frappe.session.user != self.customer_email:
			frappe.throw(_("This request is for another user."), frappe.PermissionError)
		if not self.is_open():
			frappe.throw(_("This request has expired or was already answered."))

	def end(self, reason: str | None = None) -> bool:
		"""Stops the partner's work with the customer. False when the link had already stopped."""
		if self.status in FINAL_STATUSES:
			return False

		self.update(
			{
				"status": "Ended",
				"ended_by": frappe.session.user,
				"ended_on": now(),
				"end_reason": (reason or "").strip() or None,
			}
		)
		self.save()
		return True

	def end_for_team(self, team: str, reason: str | None = None) -> bool:
		"""The customer removes its partner, or the partner stops working with a customer. The
		caller has checked billing:manage on `team`."""
		if not team or team not in (self.client_team, self.partner_team):
			frappe.throw(_("This partner link isn't on your team."), frappe.PermissionError)
		# Users never write a link directly (rule 4 of its permissions); the team's check stands in.
		self.flags.ignore_permissions = True
		return self.end(reason)

	@frappe.whitelist()
	def end_link(self, reason: str | None = None) -> bool:
		"""The desk End Link button. Saving checks write access, which only operators hold."""
		return self.end(reason)

	def _validate_status_change(self) -> None:
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status not in NEXT_STATUSES.get(before.status, ()):
			frappe.throw(_("A {0} link can't become {1}.").format(_(before.status), _(self.status)))

	def _validate_distinct_teams(self) -> None:
		if self.partner_team == self.client_team:
			frappe.throw(_("A team cannot be linked to itself as both partner and client."))

	def _validate_partner_team(self) -> None:
		if not frappe.db.exists("Partner Profile", {"team": self.partner_team, "status": "Completed"}):
			frappe.throw(_("{0} is not a registered partner team.").format(self.partner_team))

	def _validate_client_team(self) -> None:
		if not self.client_team:
			if self.status == "Active" or self.source == "Partner Code":
				frappe.throw(_("Choose the customer's team."))
			return

		# A partner's own team can't also be a client.
		if frappe.db.exists("Partner Profile", {"team": self.client_team}):
			frappe.throw(
				_("{0} is a partner team and cannot be linked as a client.").format(self.client_team)
			)

	def _validate_single_active_link(self) -> None:
		# A client team has at most one Requested or Active link at a time.
		if self.status not in ACTIVE_STATUSES or not self.client_team:
			return
		other = frappe.db.exists(
			"Partner Client Link",
			{
				"client_team": self.client_team,
				"status": ["in", ACTIVE_STATUSES],
				"name": ["!=", self.name or ""],
			},
		)
		if other:
			frappe.throw(_("{0} already has an active partner link ({1}).").format(self.client_team, other))

	def _validate_connect_fields(self) -> None:
		missing = [self.meta.get_label(field) for field in CONNECT_FIELDS if not self.get(field)]
		if missing:
			frappe.throw(_("A Connect link needs {0}.").format(", ".join(missing)))
		validate_email_address(self.customer_email, throw=True)
		if not is_connect_url(self.return_url):
			frappe.throw(_("The return URL must be on the Connect URL in Central Settings."))


def request_connect_link(
	connect_partner_id: str, engagement_id: str, customer_email: str, project_title: str, return_url: str
) -> dict:
	"""Connect's request to link a partner with the customer who hired it. The customer opens the
	returned URL to accept. A repeated call for the same project returns the same link: with a new
	URL while it waits for the customer, the earlier URL then stops working, and with its status after."""
	link = get_connect_link(engagement_id, throw=False)
	if link:
		return _reissue(link)

	partner_team = frappe.db.get_value(
		"Partner Profile", {"connect_partner_id": connect_partner_id.strip(), "status": "Completed"}, "team"
	)
	if not partner_team:
		frappe.throw(_("Partner {0} is not registered on Frappe Cloud.").format(connect_partner_id))

	link = frappe.get_doc(
		{
			"doctype": "Partner Client Link",
			"source": "Connect",
			"status": "Requested",
			"partner_team": partner_team,
			"source_reference": engagement_id.strip(),
			"customer_email": customer_email,
			"project_title": project_title.strip(),
			"return_url": return_url.strip(),
		}
	)
	token = link.issue_token()
	link.insert()
	return {"status": link.status, "url": get_customer_setup_url(token)}


def get_request_by_token(token: str | None) -> PartnerClientLink:
	name = frappe.db.get_value("Partner Client Link", {"token_hash": hash_token(token)}) if token else None
	if not name:
		frappe.throw(_("This link is not valid. Open it again from Connect."), frappe.DoesNotExistError)
	return frappe.get_doc("Partner Client Link", name)


def get_open_requests_for(user: str) -> list[str]:
	"""The Connect requests waiting for this user's answer, newest first."""
	# A system read: a request isn't on any of the user's teams yet. It is for their email only.
	return frappe.get_all(
		"Partner Client Link",
		filters={
			"source": "Connect",
			"status": "Requested",
			"customer_email": user,
			"expires_on": [">=", today()],
		},
		pluck="name",
		order_by="creation desc",
	)


def get_connect_link(engagement_id: str, throw: bool = True) -> "PartnerClientLink | None":
	"""The link Connect asked for for one of its projects, as far as the caller may see it."""
	names = frappe.get_list(
		"Partner Client Link",
		filters={"source": "Connect", "source_reference": (engagement_id or "").strip()},
		pluck="name",
		limit=1,
	)
	if names:
		return frappe.get_doc("Partner Client Link", names[0])
	if throw:
		frappe.throw(
			_("No partner link has the project {0}.").format(engagement_id), frappe.DoesNotExistError
		)
	return None


def get_customer_setup_url(token: str) -> str:
	return f"{central_url()}/dashboard/connect/customer/{token}"


def _reissue(link: PartnerClientLink) -> dict:
	if link.status == "Requested" and not link.is_open():
		link.status = "Expired"
		link.save()
	if link.status != "Requested":
		return {"status": link.status}

	token = link.issue_token()
	link.save()
	return {"status": link.status, "url": get_customer_setup_url(token)}


def on_doctype_update() -> None:
	frappe.db.add_index("Partner Client Link", ["client_team", "status"])
	frappe.db.add_index("Partner Client Link", ["partner_team", "status"])
	# One Connect project has one link, so a repeated request from Connect finds it.
	frappe.db.add_unique("Partner Client Link", ["source", "source_reference"])


def expire_requested_links() -> None:
	for name in frappe.get_all(
		"Partner Client Link", filters={"status": "Requested", "expires_on": ["<", today()]}, pluck="name"
	):
		link = frappe.get_doc("Partner Client Link", name)
		link.status = "Expired"
		link.save()
