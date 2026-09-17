from __future__ import annotations

import frappe
from frappe.model.document import Document


class Site(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cluster: DF.Link
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
		login_url: DF.SmallText | None
		login_url_expires_at: DF.Datetime | None
		pilot_credential_id: DF.Data | None
		region: DF.Data | None
		site_name: DF.Data
		status: DF.Literal["Pending", "Provisioning", "Deploying", "Running", "Failed", "Terminated"]
		subdomain: DF.Data | None
		team: DF.Link
		url: DF.Data | None
	# end: auto-generated types


def on_doctype_update():
	# Backs the team-scoped, region-grouped read in central.api.resources; runs on migrate.
	frappe.db.add_index("Site", ["team", "region"])
