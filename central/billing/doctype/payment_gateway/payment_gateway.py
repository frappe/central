# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url, now_datetime

from central.billing.gateways.base import GatewayAuthError, GatewayUnsupported


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
		if self._should_validate_credentials():
			self._validate_credentials()
		self._guard_enable()
		if self.is_enabled:
			self._enforce_default_uniqueness()

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
		"""Prove the keys, confirm the account currency, then ensure the webhook is
		registered. A GatewayAuthError here aborts the save (bad keys never persist)."""
		adapter = self.get_adapter()
		try:
			adapter.validate_credentials()
		except GatewayAuthError as e:
			frappe.throw(
				_("Gateway rejected these credentials: {0}").format(str(e)),
				title=_("Invalid Gateway Keys"),
			)

		self.credentials_validated_at = now_datetime()
		self._ensure_webhook_registered(adapter)

	def _ensure_webhook_registered(self, adapter):
		"""Auto-fill webhook_secret by registering the endpoint at the gateway.
		Gateways that can't self-register fall back to manual entry of the secret."""
		if self.webhook_endpoint_id:
			return
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

	# --- admin action --------------------------------------------------------

	@frappe.whitelist()
	def revalidate_and_register_webhook(self) -> dict:
		"""Re-check the keys and (re)create the webhook endpoint, rotating the
		signing secret. Clears the existing endpoint so a fresh one is created."""
		self.webhook_endpoint_id = None
		self._validate_credentials()
		self.save()
		return {"webhook_endpoint_id": self.webhook_endpoint_id}
