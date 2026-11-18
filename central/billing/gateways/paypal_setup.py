# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reading a PayPal setup token, part of the PayPal adapter."""

import requests

from central.billing.gateways.base import GatewayError, GatewayTimeout

# Network/server failures are transient → GatewayTimeout (retry reuses the key).
TRANSIENT = (requests.exceptions.RequestException,)

# A setup token the buyer approved, before or after Central made it a payment token.
_FINISHED_SETUP_STATUSES = ("APPROVED", "VAULTED")


class PayPalSetup:
	"""Setup reads for the PayPal adapter."""

	def read_finished_setup(self, setup_reference: str) -> dict:
		"""The setup token, once the buyer approved it, or `{}`. PayPal makes the payment
		token only on confirm, so `payment_method` is None. Read only."""
		try:
			token = self._get_setup_token(setup_reference)
		except requests.exceptions.HTTPError as e:
			if getattr(e.response, "status_code", None) == 404:
				return {}  # the setup token lapsed unused
			raise GatewayError(str(e)) from e
		except TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		if token.get("status") not in _FINISHED_SETUP_STATUSES:
			return {}
		return {"payment_method": None, "customer": (token.get("customer") or {}).get("id")}

	def _get_setup_token(self, setup_token: str) -> dict:
		resp = requests.get(
			f"{self._base()}/v3/vault/setup-tokens/{setup_token}", headers=self._headers(), timeout=30
		)
		return self._checked(resp)
