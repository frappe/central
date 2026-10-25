# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url, now_datetime

from central.billing.gateways.base import GatewayAuthError, GatewayError, GatewayUnsupported, WebhookNotFound


def _is_local_url(url: str) -> bool:
	"""A callback URL a gateway's servers can't reach — a local/dev host, so webhook
	auto-registration must be skipped (the gateway rejects such a URL)."""
	from urllib.parse import urlparse

	host = (urlparse(url).hostname or "").lower()
	if host in ("localhost", "127.0.0.1", "::1"):
		return True
	if host.endswith(".localhost") or host.endswith(".local"):
		return True
	return host.startswith(("10.", "192.168.", "127.")) or any(
		host.startswith(f"172.{block}.") for block in range(16, 32)
	)


class PaymentGateway(Document):
	"""One row per adapter, named after it (autoname: field:adapter_key).

	A second row for the same provider would be unaddressable: there is one webhook
	callback URL per adapter, so an inbound request can't say which merchant account
	it belongs to, and nothing on the row carries a routing key (team, region, legal
	entity) that a resolver could split on. Making the adapter the primary key lets
	the database enforce that rather than a validate() hook. Which currencies a
	gateway settles — and which one it is the default for — lives in the `currencies`
	child table; that is the routing dimension.
	"""

	def get_adapter(self):
		"""Resolve the GatewayAdapter for this gateway (by adapter_key).

		Lives here so callers never need to know which gateway class is in play.
		"""
		from central.billing.gateways.registry import get_adapter

		return get_adapter(self)

	def is_paypal_via_razorpay(self) -> bool:
		"""A PayPal gateway whose settlement is delegated to Razorpay (ADR 0005 path,
		re-introduced as an opt-in mode). It holds no PayPal merchant account, so it
		needs no PayPal keys/webhook of its own — the money moves through, and is
		reconciled against, the configured Razorpay gateway."""
		return self.adapter_key == "Paypal" and self.paypal_settlement_mode == "Via Razorpay"

	def validate(self):
		self._enforce_regulatory_ceiling()
		if self._should_validate_credentials():
			self._validate_credentials()
		self._guard_enable()
		if self.is_enabled:
			self._enforce_default_uniqueness()

	def _enforce_regulatory_ceiling(self):
		"""Hold every regulated currency at the ceiling the law gives it (ADR 0022).

		The ₹15,000 silent-debit limit is an RBI rule, so it is not an admin's number
		to raise or to leave blank: an empty ceiling reads as "no ceiling", which
		would let us pull an INR debit that the bank will decline and the regulator
		will not forgive. A stricter number is a business decision and is left alone.
		"""
		from central.billing.gateways import capabilities

		for row in self.currencies or []:
			ceiling = capabilities.regulatory_ceiling(row.currency)
			if ceiling is None:
				continue
			configured = frappe.utils.flt(row.max_silent_charge)
			row.max_silent_charge = min(configured, ceiling) if configured else ceiling
			# The flag means *we* owe the notice and the 24h hold. Where the gateway
			# does it itself — Stripe's India flow notifies on confirm and holds the
			# intent 26 hours — arming ours on top delays the charge by two days and
			# tells the customer twice (ADR 0023).
			row.requires_predebit_notice = 0 if capabilities.self_notifies(self.name) else 1

	def _enforce_default_uniqueness(self):
		"""At most one enabled gateway may have is_default = True per currency.

		When this gateway sets is_default = True on a currency row, clear that flag
		on every other enabled gateway's row for the same currency. This mirrors
		radio-button semantics scoped per currency."""
		for row in self.currencies or []:
			if not row.is_default:
				continue
			# Find any other gateway currency row with is_default for the same currency.
			others = frappe.db.get_all(
				"Payment Gateway Currency",
				filters={
					"currency": row.currency,
					"is_default": 1,
					"parent": ["!=", self.name],
				},
				fields=["name", "parent"],
			)
			for other in others:
				if frappe.db.get_value("Payment Gateway", other.parent, "is_enabled"):
					frappe.db.set_value(
						"Payment Gateway Currency", other.name, "is_default", 0, update_modified=False
					)

	# --- credential validation + webhook auto-registration -------------------

	def _validation_active(self) -> bool:
		"""Whether setup validation runs at all. A setup-time admin action must not
		depend on a live gateway, so it's off under tests/seeds unless opted in."""
		if self.flags.get("skip_credential_validation"):
			return False
		if frappe.flags.in_test and not self.flags.get("force_credential_validation"):
			return False
		return True

	def _should_validate_credentials(self) -> bool:
		"""Validate only when freshly-typed keys are present — so unrelated edits
		don't hammer the gateway. A Via-Razorpay PayPal row carries no keys of its
		own, so there is nothing to validate (settlement runs on Razorpay)."""
		if self.is_paypal_via_razorpay():
			return False
		return self._validation_active() and self._credentials_entered()

	def _credentials_entered(self) -> bool:
		"""True when api_key/api_secret hold freshly-typed plaintext, not the
		'*****' mask Frappe substitutes for an unchanged Password field."""
		return any(
			self.get(field) and not self.is_dummy_password(self.get(field))
			for field in ("api_key", "api_secret")
		)

	def _validate_credentials(self):
		"""Prove the keys, then make sure their account sends us our webhook events.
		A GatewayAuthError here aborts the save (bad keys never persist)."""
		adapter = self.get_adapter()
		try:
			adapter.validate_credentials()
		except GatewayAuthError as e:
			frappe.throw(
				_("Gateway rejected these credentials: {0}").format(str(e)),
				title=_("Invalid Gateway Keys"),
			)

		self.credentials_validated_at = now_datetime()
		self._sync_webhook(adapter)

	def _sync_webhook(self, adapter):
		"""Keep the endpoint when the new keys can see it, and register one when they cannot.

		New keys for the same account only update the endpoint's events. Keys for another
		account, or another Stripe mode, cannot see the stored endpoint, so a new one is
		registered there. The old endpoint is never deleted: another site may use it.
		"""
		if self.webhook_endpoint_id:
			try:
				self._subscribe_missing_events(adapter)
				return
			except GatewayUnsupported:
				return
			except WebhookNotFound:
				self._forget_previous_endpoint()
			except GatewayError as e:
				# The keys are proven; a failed webhook read must not block saving them.
				frappe.msgprint(
					_("Could not check the webhook: {0}. Use Pull Webhook Events later.").format(str(e)),
					title=_("Webhook Not Checked"),
					indicator="orange",
				)
				return
		self._register_webhook(adapter)

	def _subscribe_missing_events(self, adapter):
		"""Add the events Central needs to the stored endpoint, if any are missing."""
		webhook = adapter.get_webhook(self.webhook_endpoint_id)
		events = webhook["events"]
		if not set(adapter.webhook_events) <= set(events) and "*" not in events:
			events = list(adapter.webhook_events)
			adapter.update_webhook_events(self.webhook_endpoint_id, self.webhook_callback_url(), events)
		self._record_webhook(webhook["url"], webhook["is_active"], events)

	def _forget_previous_endpoint(self):
		frappe.msgprint(
			_(
				"Webhook endpoint {0} is not in the account of the new keys, so a new endpoint is "
				"registered. The old endpoint is not deleted. Remove it in the old account if no "
				"other site uses it."
			).format(self.webhook_endpoint_id),
			title=_("Gateway Account Changed"),
			indicator="orange",
		)
		self.webhook_endpoint_id = None

	def _register_webhook(self, adapter):
		"""Register the endpoint at the gateway and store its signing secret.
		Gateways that can't self-register fall back to manual entry of the secret."""
		url = self.webhook_callback_url()
		# The gateway's servers must be able to reach the callback. On a local/dev
		# host (localhost, *.localhost, loopback/private IP) they can't — and the
		# gateway rejects the registration — so skip it with a note. Keys still
		# validate; the webhook secret can be set manually (or registered once the
		# site is public).
		if _is_local_url(url):
			frappe.msgprint(
				_(
					"Webhook not auto-registered — {0} isn't publicly reachable. "
					"Enter the webhook secret manually, or register it once the site is public."
				).format(url),
				title=_("Webhook Registration Skipped"),
				indicator="orange",
			)
			return
		try:
			result = adapter.register_webhook(url)
		except GatewayUnsupported:
			return
		self.webhook_endpoint_id = result.get("endpoint_id")
		secret = result.get("secret")
		if secret:
			self.webhook_secret = secret
		self._record_webhook(url, True, list(adapter.webhook_events))

	def _record_webhook(self, url: str, is_active: bool, events: list[str]):
		"""Store what the gateway reports for the endpoint, one row for each event."""
		needed = set(self.get_adapter().webhook_events)
		subscribed = set(events)
		self.webhook_url = url
		self.is_webhook_active = int(bool(is_active))
		self.webhook_events_pulled_at = now_datetime()
		self.set("webhook_events", [])
		for event in sorted(needed | subscribed):
			is_needed = event in needed
			is_subscribed = event in subscribed or "*" in subscribed
			self.append(
				"webhook_events",
				{
					"event_type": event,
					"is_needed": int(is_needed),
					"is_subscribed": int(is_subscribed),
					"state": "Not Used" if not is_needed else ("OK" if is_subscribed else "Missing"),
				},
			)

	def webhook_callback_url(self) -> str:
		return f"{get_url()}/api/method/central.billing.payments.webhooks.{self.adapter_key.lower()}"

	def _guard_enable(self):
		"""A gateway only goes live once its keys have proven out — otherwise an
		inbound webhook has no secret to verify against and charges can't settle."""
		if not self._validation_active():
			return
		# Via-Razorpay PayPal settles on Razorpay, which carries its own validated
		# keys — this row needs none, so don't block enabling it on a validation it
		# can never have.
		if self.is_paypal_via_razorpay():
			return
		if self.is_enabled and not self.credentials_validated_at:
			frappe.throw(
				_("Validate the gateway credentials before enabling it."),
				title=_("Gateway Not Validated"),
			)
		# A webhook with no secret to check it against would be accepted from anyone.
		if self.is_enabled and not self._has_webhook_secret():
			frappe.throw(
				_("Register the webhook, or enter its secret, before enabling the gateway."),
				title=_("Webhook Secret Missing"),
			)

	def _has_webhook_secret(self) -> bool:
		"""Whether a webhook secret is set: typed now, stored (the field then holds a mask),
		or in site config."""
		return bool(self.webhook_secret or self.get_adapter().get_credential("webhook_secret"))

	# --- admin actions -------------------------------------------------------

	@frappe.whitelist(methods=["POST"])
	def pull_webhook_events(self) -> dict:
		"""Read the endpoint from the gateway and list the events it sends."""
		self.check_permission("write")
		webhook = self._read_webhook()
		self._record_webhook(webhook["url"], webhook["is_active"], webhook["events"])
		self.save()
		return self._webhook_report()

	@frappe.whitelist(methods=["POST"])
	def update_webhook_events(self) -> dict:
		"""Subscribe the endpoint to exactly the events Central needs, then read it back.
		The signing secret does not change."""
		self.check_permission("write")
		self._read_webhook()
		adapter = self.get_adapter()
		try:
			adapter.update_webhook_events(
				self.webhook_endpoint_id, self.webhook_callback_url(), list(adapter.webhook_events)
			)
		except GatewayError as e:
			frappe.throw(_("The gateway did not update the webhook: {0}").format(str(e)))
		return self.pull_webhook_events()

	def _read_webhook(self) -> dict:
		"""The endpoint as the gateway reports it, or a message the operator can act on."""
		if self.is_paypal_via_razorpay():
			frappe.throw(_("This gateway settles through Razorpay and has no webhook of its own."))
		if not self.webhook_endpoint_id:
			frappe.throw(_("No webhook endpoint is registered. Use Re-register Webhook."))
		try:
			return self.get_adapter().get_webhook(self.webhook_endpoint_id)
		except WebhookNotFound:
			frappe.throw(
				_(
					"Webhook endpoint {0} is not in the account of these keys. Use Re-register Webhook."
				).format(self.webhook_endpoint_id)
			)
		except GatewayUnsupported:
			frappe.throw(_("Central cannot read the webhook of this gateway."))
		except GatewayError as e:
			frappe.throw(_("The gateway did not return the webhook: {0}").format(str(e)))

	def _webhook_report(self) -> dict:
		return {
			"missing": [row.event_type for row in self.webhook_events if row.state == "Missing"],
			"not_used": [row.event_type for row in self.webhook_events if row.state == "Not Used"],
			"is_active": bool(self.is_webhook_active),
			"url_matches": self.webhook_url == self.webhook_callback_url(),
			"expected_url": self.webhook_callback_url(),
		}

	@frappe.whitelist(methods=["POST"])
	def revalidate_and_register_webhook(self) -> dict:
		"""Re-check the keys and register a new webhook endpoint with a new signing secret.

		The old endpoint is not deleted at the gateway. When no new endpoint is registered
		(a local site, or a gateway that cannot register one), the old one is kept.
		"""
		self.check_permission("write")
		if self.is_paypal_via_razorpay():
			frappe.throw(_("This gateway settles through Razorpay and has no webhook of its own."))

		previous = self.webhook_endpoint_id
		self.webhook_endpoint_id = None
		try:
			self._validate_credentials()
		except GatewayError as e:
			frappe.throw(_("The gateway did not register the webhook: {0}").format(str(e)))
		registered = bool(self.webhook_endpoint_id)
		if not registered:
			self.webhook_endpoint_id = previous
		self.save()
		return {
			"registered": registered,
			"webhook_endpoint_id": self.webhook_endpoint_id,
			"previous": previous,
		}
