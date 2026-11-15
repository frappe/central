# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, get_datetime, get_first_day, get_last_day, getdate, now

from central.iam import PARTNER_ROLES, can, user_has_operator_bypass

REFERENCE_MAX_LENGTH = 140
END_REASON_MAX_LENGTH = 500
# Only the link actions change these after the link exists.
ACTION_FIELDS = (
	"status",
	"role",
	"linked_by",
	"linked_on",
	"reference",
	"ended_by",
	"ended_on",
	"end_reason",
	"payer",
	"partner_pays_from",
	"partner_pays_until",
)
# Who may make each change of who pays: the customer side, the partner side, or either.
PAYER_CHANGES = {
	("Customer", "Partner Requested"): "customer",
	("Partner Requested", "Partner"): "partner",
	("Partner Requested", "Customer"): "either",
	("Partner", "Customer"): "either",
}


class PartnerLink(Document):
	"""The relationship between one partner team and one customer team. The customer starts it
	with the partner code and chooses its role, and either side ends it. An ended link never
	becomes active again."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		customer_team: DF.Link
		end_reason: DF.SmallText | None
		ended_by: DF.Link | None
		ended_on: DF.Datetime | None
		linked_by: DF.Link | None
		linked_on: DF.Datetime | None
		partner_pays_from: DF.Date | None
		partner_pays_until: DF.Date | None
		partner_team: DF.Link
		payer: DF.Literal["Customer", "Partner Requested", "Partner"]
		reference: DF.Data | None
		role: DF.Link
		status: DF.Literal["Active", "Ended"]
	# end: auto-generated types

	@classmethod
	def add(cls, customer_team: str, partner_code: str, reference: str | None = None) -> "PartnerLink":
		"""Link `customer_team` to the partner that owns `partner_code`."""
		link = frappe.get_doc(
			{
				"doctype": "Partner Link",
				"customer_team": customer_team,
				"partner_team": get_partner_team_by_code(partner_code),
				"reference": reference,
			}
		)
		link.flags.from_partner_code = True
		return link.insert()

	def before_insert(self) -> None:
		self.status = "Active"
		self.linked_by = frappe.session.user
		self.linked_on = now()
		self.reference = (self.reference or "").strip()[:REFERENCE_MAX_LENGTH] or None
		self.ended_by = self.ended_on = self.end_reason = None

	def validate(self) -> None:
		if self.role not in PARTNER_ROLES:
			frappe.throw(_("A partner can have the Viewer or the Developer role."))
		if self.is_new():
			self._validate_new_link()
		else:
			self._validate_update()

	def _validate_new_link(self) -> None:
		if not self.flags.from_partner_code and not user_has_operator_bypass():
			frappe.throw(_("Add a partner with its partner code."), frappe.PermissionError)
		if self.partner_team == self.customer_team:
			frappe.throw(_("A team cannot add itself as its partner."))
		if not frappe.db.get_value("Team", self.partner_team, "connect_partner_id"):
			frappe.throw(_("This team is not a Frappe partner."))
		if frappe.db.get_value("Team", self.customer_team, "connect_partner_id"):
			frappe.throw(_("A partner team cannot add a partner."))

		# Lock the customer team, so two requests cannot both add a partner to it.
		frappe.db.get_value("Team", self.customer_team, "name", for_update=True)
		current = frappe.db.get_value(
			"Partner Link", {"customer_team": self.customer_team, "status": "Active"}, "partner_team"
		)
		if current:
			frappe.throw(_("This team already has a partner. End that link before you add another partner."))

	def _validate_update(self) -> None:
		previous = self.get_doc_before_save()
		if previous and previous.status == "Ended":
			frappe.throw(_("An ended partner link cannot change. Add the partner again to start a new link."))
		if self.flags.from_link_action or user_has_operator_bypass():
			return
		if previous and any(self.get(field) != previous.get(field) for field in ACTION_FIELDS):
			frappe.throw(_("Use the partner link actions to change this link."), frappe.PermissionError)

	# Internal; the HTTP surfaces are central.api.partners.end_partner_link and
	# central.api.connect.end_partner_link.
	def end(self, reason: str) -> bool:
		"""End the link. Returns False when it had already ended."""
		if self.status == "Ended":
			return False

		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("Enter the reason for ending the partner link."))

		self.update(
			{
				"status": "Ended",
				"ended_by": frappe.session.user,
				"ended_on": now(),
				"end_reason": reason[:END_REASON_MAX_LENGTH],
				"payer": "Customer",
			}
		)
		self._set_partner_pays_dates()
		self.flags.from_link_action = True
		self.save()

		return True

	# Internal; the HTTP surface is central.api.partners.set_partner_payer.
	def set_payer(self, payer: str) -> None:
		"""Change who pays the customer team's usage.

		1. The customer asks its partner to pay: Customer to Partner Requested.
		2. The partner accepts: Partner Requested to Partner.
		3. Either side declines a request, or stops partner pays: back to Customer.
		A change takes effect on the 1st of the next month, see _set_partner_pays_dates."""
		side = PAYER_CHANGES.get((self.payer, payer))
		if not side or self.status != "Active":
			frappe.throw(_("Who pays cannot change from {0} to {1}.").format(self.payer, payer))
		if not self._is_on_side(side):
			frappe.throw(_("Your team cannot make this change of who pays."), frappe.PermissionError)

		self.payer = payer
		self._set_partner_pays_dates()
		self.flags.from_link_action = True
		self.save()

	def _is_on_side(self, side: str) -> bool:
		user = frappe.session.user
		if user_has_operator_bypass(user):
			return True

		is_customer = can(user, self.customer_team, "team:manage_partners")
		is_partner = can(user, self.partner_team, "team:manage_partners")
		return {"customer": is_customer, "partner": is_partner, "either": is_customer or is_partner}[side]

	def _set_partner_pays_dates(self) -> None:
		"""A partner pays from the 1st of the month after it accepts. When it stops, it pays to
		the end of the current month, so every month has one payer. A stop before the partner
		started paying cancels the payment."""
		today = getdate()
		is_paying = bool(
			self.partner_pays_from
			and getdate(self.partner_pays_from) <= today
			and (not self.partner_pays_until or getdate(self.partner_pays_until) >= today)
		)
		if self.payer == "Partner":
			if is_paying:
				self.partner_pays_until = None
			else:
				self.partner_pays_from, self.partner_pays_until = get_first_day(add_months(today, 1)), None
		elif is_paying:
			self.partner_pays_until = self.partner_pays_until or get_last_day(today)
		elif self.partner_pays_from and getdate(self.partner_pays_from) > today:
			self.partner_pays_from = self.partner_pays_until = None

	# Internal; the HTTP surface is central.api.partners.set_partner_role.
	def set_role(self, role: str) -> None:
		"""Change what the partner can do. Only the customer side decides it."""
		user = frappe.session.user
		if not user_has_operator_bypass(user) and not can(user, self.customer_team, "team:manage_partners"):
			frappe.throw(_("Only the customer team can change the partner's access."), frappe.PermissionError)

		self.role = role
		self.flags.from_link_action = True
		self.save()

	def on_update(self) -> None:
		if self.has_value_changed("status") and self.status == "Ended":
			self._notify_end()

	def _notify_end(self) -> None:
		"""Tell the partner managers of both teams why the link ended."""
		from central.notification.engine import dispatch

		names = dict(
			frappe.get_all(
				"Team",
				filters={"name": ("in", (self.customer_team, self.partner_team))},
				fields=["name", "team_name"],
				as_list=True,
			)
		)
		context = {"customer_name": names[self.customer_team], "partner_name": names[self.partner_team]}
		for team in (self.customer_team, self.partner_team):
			dispatch(
				team,
				"partner_link_ended",
				message=self.end_reason,
				context=context,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	def get_summary(self) -> dict:
		return summarize_links([self])[0]


LINK_FIELDS = [
	"name",
	"status",
	"role",
	"reference",
	"linked_on",
	"ended_on",
	"customer_team",
	"partner_team",
	"payer",
	"partner_pays_from",
	"partner_pays_until",
]


def summarize_links(links: list) -> list[dict]:
	"""Each link as the consoles and Connect read it, with both teams' names, in one Team query."""
	names = {link.customer_team for link in links} | {link.partner_team for link in links}
	teams = {
		row.name: row
		for row in frappe.get_all(
			"Team",
			filters={"name": ("in", list(names))},
			fields=["name", "team_name", "team_logo", "owner_user"],
		)
	}
	return [
		{
			**{field: link.get(field) for field in LINK_FIELDS},
			"partner_name": teams[link.partner_team].team_name,
			"partner_logo": teams[link.partner_team].team_logo,
			"customer_name": teams[link.customer_team].team_name,
			"customer_logo": teams[link.customer_team].team_logo,
			"customer_email": teams[link.customer_team].owner_user,
		}
		for link in links
	]


def get_partner_team_by_code(partner_code: str) -> str:
	"""The Active partner team that owns `partner_code`."""
	code = (partner_code or "").strip().upper()
	team = (
		frappe.db.get_value(
			"Team",
			{"partner_code": code, "status": "Active", "connect_partner_id": ("is", "set")},
		)
		if code
		else None
	)
	if not team:
		frappe.throw(
			_("No partner has this code. Check the code with your partner."), frappe.DoesNotExistError
		)

	return team


def get_active_link_name(customer_team: str) -> str | None:
	return frappe.db.get_value("Partner Link", {"customer_team": customer_team, "status": "Active"})


def reprice_paid_customers() -> None:
	"""Daily: a change of who pays takes effect on the 1st of a month. Price each customer whose
	payer changed in the last week in the new payer's currency, from the day of the change.
	Running it again changes nothing, because a price already in that currency stays."""
	from central.billing.catalog.subscriptions import reprice_team

	today = getdate()
	since = add_days(today, -7)
	link = frappe.qb.DocType("Partner Link")
	rows = (
		frappe.qb.from_(link)
		.select(link.customer_team, link.partner_pays_from, link.partner_pays_until)
		.where(
			link.partner_pays_from.between(since, today)
			| link.partner_pays_until.between(add_days(since, -1), add_days(today, -1))
		)
	).run(as_dict=True)

	for row in rows:
		for day in _payer_change_days(row, since, today):
			try:
				reprice_team(row.customer_team, get_datetime(day))
				frappe.db.commit()  # nosemgrep: one team's failure must not undo the others
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"Could not price {row.customer_team} for its new payer")


def _payer_change_days(row, since, today) -> list:
	"""The days in the window on which the team's payer changed."""
	days = []
	if row.partner_pays_from and since <= getdate(row.partner_pays_from) <= today:
		days.append(getdate(row.partner_pays_from))
	if row.partner_pays_until:
		day_after = add_days(getdate(row.partner_pays_until), 1)
		if since <= day_after <= today:
			days.append(day_after)
	return sorted(days)
