# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from central.integrations.grove import GroveClient

WEBHOOK_NAME = "Grove Team Tier"
WEBHOOK_METHOD = "grove.api.teams.team_webhook"
# Names the control user at Grove by its api_key; the body's HMAC is Frappe's own header.
CONTROL_KEY_HEADER = "X-Grove-Control-Key"
# The body is get_team_limits (hooks.jinja), rendered when the delivery runs. The condition
# fires on a level set, changed or cleared; a profile inserted without one is silent.
TEAM_TIER_WEBHOOK = {
	"webhook_doctype": "Billing Profile",
	"webhook_docevent": "on_update",
	"condition": 'doc.has_value_changed("trust_tier_level") and (doc.trust_tier_level or doc.get_doc_before_save())',
	"request_structure": "JSON",
	"webhook_json": "{{ json.dumps(get_team_limits(doc.team)) }}",
	"request_method": "POST",
	"timeout": 30,
	# About 48 hours on Frappe's retry schedule, then Exhausted in the Webhook Request Log.
	"max_retries": 5,
}


class AISettings(Document):
	"""Where Grove is, the control credential Central calls it with, and the Webhook that
	carries a team's tier there."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		base_url: DF.Data | None
		control_api_key: DF.Data | None
		control_api_secret: DF.Password | None
		trial_key_cap: DF.Currency
		trial_key_geography: DF.Data | None
		trial_model_group: DF.Data | None
		trial_pool_size: DF.Int
	# end: auto-generated types

	@property
	def is_enrolled(self) -> bool:
		return bool(self.base_url and self.control_api_key)

	def validate(self) -> None:
		self.base_url = (self.base_url or "").strip().rstrip("/")
		if flt(self.trial_key_cap) != cint(self.trial_key_cap):
			frappe.throw(_("Trial Key Cap is whole US dollars."))
		if self.trial_pool_size and not self.trial_key_geography:
			frappe.throw(_("Set Trial Key Geography before sizing the pool."))

	def on_update(self) -> None:
		self.sync_webhook()

	def set_credential(self, credential: dict) -> None:
		self.control_api_key = credential["api_key"]
		self.control_api_secret = credential["api_secret"]
		self.save()

	def sync_webhook(self) -> None:
		"""The Webhook that sends a Billing Profile's level to Grove, kept in step with the URL
		and the credential: enabled and signed with the control secret once enrolled, saved
		disabled before that, and not made until there is a URL to point it at."""
		if frappe.db.exists("Webhook", WEBHOOK_NAME):
			webhook = frappe.get_doc("Webhook", WEBHOOK_NAME)
		elif self.base_url:
			webhook = frappe.get_doc({"doctype": "Webhook", "__newname": WEBHOOK_NAME})
		else:
			return
		if self.base_url:
			webhook.request_url = f"{self.base_url}/api/method/{WEBHOOK_METHOD}"
		webhook.update(
			{
				**TEAM_TIER_WEBHOOK,
				"enabled": int(self.is_enrolled),
				"enable_security": int(self.is_enrolled),
				"webhook_secret": self.get_password("control_api_secret") if self.is_enrolled else None,
				"webhook_headers": [
					{"key": "Content-Type", "value": "application/json"},
					{"key": CONTROL_KEY_HEADER, "value": self.control_api_key},
				],
			}
		)
		webhook.save(ignore_permissions=True)


def sync_webhook() -> None:
	"""after_migrate: the Webhook follows an edit to its spec."""
	frappe.get_single("AI Settings").sync_webhook()


# Plain whitelisted calls, not doc methods: a form's doc method gets its arguments nested
# under `args`, where a secret cannot be popped from the request before it is logged.


@frappe.whitelist(methods=["POST"])
def enroll() -> None:
	"""Desk button: exchange the bootstrap secret Grove was given for Central's own control
	credential. The secret is popped from the raw request, so it is never logged."""
	frappe.only_for("System Manager")
	secret = frappe.local.form_dict.pop("bootstrap_secret", None)
	if not secret:
		frappe.throw(_("Bootstrap secret is required."))

	settings = frappe.get_single("AI Settings")
	if not settings.base_url:
		frappe.throw(_("Set the Grove URL first."))

	settings.set_credential(GroveClient.enroll(settings.base_url, secret))


@frappe.whitelist(methods=["POST"])
def rotate_credential() -> None:
	"""Desk button: a new control secret from Grove. The old one stops at once."""
	frappe.only_for("System Manager")
	frappe.get_single("AI Settings").set_credential(GroveClient.from_settings().rotate_control_key())
