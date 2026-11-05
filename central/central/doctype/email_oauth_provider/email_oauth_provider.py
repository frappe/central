# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmailOAuthProvider(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.integrations.doctype.oauth_scope.oauth_scope import OAuthScope
		from frappe.integrations.doctype.query_parameters.query_parameters import QueryParameters
		from frappe.types import DF

		authorize_url: DF.Data
		client_id: DF.Data | None
		client_secret: DF.Password | None
		enabled: DF.Check
		provider: DF.Data
		query_parameters: DF.Table[QueryParameters]
		scopes: DF.Table[OAuthScope]
		token_url: DF.Data
	# end: auto-generated types

	def validate(self):
		for field in ("authorize_url", "token_url"):
			if not self.get(field).startswith("https://"):
				frappe.throw(
					_("{0} must start with https://").format(_(self.meta.get_label(field))),
					title=_("Invalid URL"),
				)
		if self.enabled and not (
			self.client_id and self.get_password("client_secret", raise_exception=False)
		):
			frappe.throw(
				_("Add the Client ID and Client Secret before enabling {0}").format(self.provider),
				title=_("Missing credentials"),
			)

	def get_scopes(self) -> list[str]:
		return [row.scope for row in self.scopes]

	def get_query_params(self) -> dict[str, str]:
		return {row.key: row.value for row in self.query_parameters}
