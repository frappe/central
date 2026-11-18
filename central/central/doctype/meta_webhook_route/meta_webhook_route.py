# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MetaWebhookRoute(Document):
	"""Which site gets the Meta webhooks of one WhatsApp Business Account, and the secret Central signs them with."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		server: DF.Link | None
		site: DF.Link
		team: DF.Link
		waba_id: DF.Data
		webhook_secret: DF.Password | None
	# end: auto-generated types
