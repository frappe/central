# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.website.utils import cleanup_page_name

# The sources a new site starts with. Operators add, rename or disable them in Desk.
STARTING_SOURCES = (
	"Frappe Forum",
	"Frappe School",
	"Frappe Blog",
	"Frappe Docs",
	"YouTube",
	"LinkedIn",
	"Instagram",
	"X",
	"Reddit",
	"Newsletter",
)


class AffiliateSource(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		title: DF.Data
	# end: auto-generated types

	def autoname(self) -> None:
		# The ID goes in shared links, so it is made from the title once and never follows a rename.
		self.name = cleanup_page_name(self.title)


def ensure_affiliate_sources() -> None:
	"""Seed the starting sources when none exist yet, so an operator's edits are never undone."""
	if frappe.db.count("Affiliate Source"):
		return

	for title in STARTING_SOURCES:
		frappe.get_doc({"doctype": "Affiliate Source", "title": title}).insert()
