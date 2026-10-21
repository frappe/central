# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re
from typing import Self

import frappe
from frappe import _
from frappe.model.document import Document

from central.signups.doctype.affiliate.affiliate import generate_affiliate_code
from central.signups.doctype.product.product import get_enabled_product_key
from central.site_provisioning import UTM_LENGTH, clip

SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]")
LINKS_PER_AFFILIATE = 100


class AffiliateLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		affiliate: DF.Link
		product: DF.Link | None
		slug: DF.Data
		utm_campaign: DF.Data | None
		utm_source: DF.Data | None
	# end: auto-generated types

	@classmethod
	def create_for(
		cls,
		affiliate: str,
		slug: str | None = None,
		product: str | None = None,
		utm_source: str | None = None,
		utm_campaign: str | None = None,
	) -> Self:
		"""A new named link of the affiliate. An empty slug gets a random one."""
		if frappe.db.count("Affiliate Link", {"affiliate": affiliate}) >= LINKS_PER_AFFILIATE:
			frappe.throw(_("You can have at most {0} links.").format(LINKS_PER_AFFILIATE))

		product_key = get_enabled_product_key(product)
		if product and not product_key:
			frappe.throw(_("This product is not available."))

		campaign = clip(utm_campaign, UTM_LENGTH)
		if not campaign:
			frappe.throw(_("Give the link a campaign."))

		link = frappe.get_doc(
			{
				"doctype": "Affiliate Link",
				"affiliate": affiliate,
				"slug": (slug or "").strip().lower() or generate_affiliate_code(),
				"product": product_key,
				"utm_source": clip(utm_source, UTM_LENGTH),
				"utm_campaign": campaign,
			}
		)
		if frappe.db.exists("Affiliate Link", link.slug):
			raise_slug_taken(link.slug)

		try:
			# An affiliate holds no permission on links, and creates only their own.
			return link.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# A concurrent request took the slug after the check. Drop Frappe's "already exists" message.
			frappe.clear_last_message()
			raise_slug_taken(link.slug)

	def validate(self) -> None:
		if not SLUG_PATTERN.fullmatch(self.slug or ""):
			frappe.throw(
				_("Use 3 to 32 lowercase letters, numbers and hyphens, starting and ending with one.")
			)

		# A slug and a main code share /r/, so one must never take the other's name.
		if frappe.db.exists("Affiliate", {"affiliate_code": self.slug}):
			raise_slug_taken(self.slug)


def raise_slug_taken(slug: str) -> None:
	frappe.throw(_("The link name {0} is taken. Choose another.").format(slug))
