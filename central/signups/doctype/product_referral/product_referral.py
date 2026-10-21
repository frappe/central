# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import Self

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_datetime, now_datetime

from central.iam import get_user_team_names
from central.signups.doctype.affiliate_visit.affiliate_visit import UTM_FIELDS
from central.signups.doctype.product.product import FRAPPE_CLOUD_PRODUCT_KEY


class ProductReferral(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		affiliate: DF.Link
		product: DF.Link | None
		referred_team: DF.Link
		utm_campaign: DF.Data | None
		utm_medium: DF.Data | None
		utm_source: DF.Data | None
		visit: DF.Link | None
	# end: auto-generated types

	@classmethod
	def record(cls, team: str, product: str | None, visit: str) -> Self | None:
		"""Credit the visit's affiliate with the team's signup for the product, when the visit
		still counts. A visit with no product, from a plain link, counts for any product. The first
		referral for a team and product is final."""
		if frappe.db.exists("Product Referral", referral_name(team, product)):
			return None

		row = frappe.db.get_value(
			"Affiliate Visit", visit, ["affiliate", "product", "last_clicked_on", *UTM_FIELDS], as_dict=True
		)
		if not row or (row.product and row.product != product) or not is_creditable(team, row):
			return None

		referral = frappe.get_doc(
			{
				"doctype": "Product Referral",
				"referred_team": team,
				"product": product,
				"affiliate": row.affiliate,
				"visit": visit,
				**{field: row[field] for field in UTM_FIELDS},
			}
		)
		# The new customer signs up, and holds no permission on referrals.
		return referral.insert(ignore_permissions=True)

	def after_insert(self) -> None:
		# A plain link's visit takes the product the person chose, so the click counts for it.
		if self.product and self.visit:
			frappe.db.set_value(
				"Affiliate Visit",
				{"name": self.visit, "product": ["is", "not set"]},
				"product",
				self.product,
				update_modified=False,
			)

	def autoname(self) -> None:
		# The name is the unique key, so the database rejects a second referral for a team and product.
		self.name = referral_name(self.referred_team, self.product)


def referral_name(team: str, product: str | None) -> str:
	return f"{team}::{product or FRAPPE_CLOUD_PRODUCT_KEY}"


def is_creditable(team: str, visit: dict) -> bool:
	"""Whether the visit's affiliate is Active, the click is within the cookie window, and the
	affiliate is not a member of the team they would be credited for."""
	affiliate = frappe.db.get_value("Affiliate", visit["affiliate"], ["status", "user"], as_dict=True)
	days = cint(frappe.db.get_single_value("Central Settings", "affiliate_cookie_days"))

	return (
		bool(affiliate)
		and affiliate.status == "Active"
		and get_datetime(visit["last_clicked_on"]) >= add_days(now_datetime(), -days)
		and team not in get_user_team_names(affiliate.user)
	)
