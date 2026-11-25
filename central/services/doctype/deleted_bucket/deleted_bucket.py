# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.model.document import Document

# Usage for a deleted bucket arrives within days, so a month of rows is plenty.
KEPT_DAYS = 30


class DeletedBucket(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		deleted_at: DF.Datetime
		external_id: DF.Data
		region: DF.Link | None
		subscription: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	pass


def record_deleted_bucket(service) -> None:
	"""Note that a team deleted the bucket of `service`, and the subscription that billed it."""
	record = frappe.get_doc(
		{
			"doctype": "Deleted Bucket",
			"external_id": service.external_id,
			"team": service.team,
			"subscription": service.subscription,
			"region": service.region,
			"deleted_at": frappe.utils.now_datetime(),
		}
	)
	# The user deleting their bucket cannot write this system record themselves.
	record.insert(ignore_permissions=True)


def prune_deleted_buckets(now=None) -> None:
	"""Daily: delete rows older than the kept days."""
	cutoff = frappe.utils.get_datetime(now or frappe.utils.now_datetime()) - datetime.timedelta(
		days=KEPT_DAYS
	)
	table = frappe.qb.DocType("Deleted Bucket")
	frappe.qb.from_(table).delete().where(table.deleted_at < cutoff).run()
