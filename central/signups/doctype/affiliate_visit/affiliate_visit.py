# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from central.geo import get_country_from_ip

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign")


class AffiliateVisit(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		affiliate: DF.Link
		country: DF.Data | None
		last_clicked_on: DF.Datetime
		link: DF.Link | None
		product: DF.Link | None
		utm_campaign: DF.Data | None
		utm_medium: DF.Data | None
		utm_source: DF.Data | None
	# end: auto-generated types

	@classmethod
	def record_click(
		cls, affiliate: str, link: str | None, product: str | None, utm: dict, earlier: str | None
	) -> str:
		"""The visit a click belongs to. A click like the browser's earlier one reuses that visit."""
		values = {"affiliate": affiliate, "link": link, "product": product, **utm}
		row = frappe.db.get_value("Affiliate Visit", earlier, list(values), as_dict=True) if earlier else None
		if row and all((row[field] or None) == (value or None) for field, value in values.items()):
			frappe.db.set_value("Affiliate Visit", earlier, "last_clicked_on", now_datetime())
			return earlier

		visit = frappe.get_doc({"doctype": "Affiliate Visit", **values, "last_clicked_on": now_datetime()})
		# A guest clicks the link, and a visit holds nothing personal.
		visit.insert(ignore_permissions=True)
		if ip := frappe.local.request_ip:
			# The lookup can call a remote service, so the redirect does not wait for it.
			frappe.enqueue(set_country, visit=visit.name, ip=ip, queue="short", enqueue_after_commit=True)

		return visit.name


def set_country(visit: str, ip: str) -> None:
	"""Record the visitor's country. The IP address is used here and never stored."""
	if country := get_country_from_ip(ip):
		frappe.db.set_value("Affiliate Visit", visit, "country", country, update_modified=False)
