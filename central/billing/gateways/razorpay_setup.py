# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reading and undoing a Razorpay setup, part of the Razorpay adapter."""

import razorpay
import requests

from central.billing.gateways.base import GatewayError, GatewayTimeout

# Razorpay raises these for transient/server failures; a refused request is BadRequestError.
TRANSIENT = (razorpay.errors.GatewayError, razorpay.errors.ServerError, requests.exceptions.RequestException)


class RazorpaySetup:
	"""Setup reads and token removal for the Razorpay adapter."""

	def read_finished_setup(self, setup_reference: str) -> dict:
		"""The payment that authorised a token on the setup order, or `{}`. Read only.
		An order Razorpay does not have saved nothing."""
		try:
			payments = order_payments(self._client(), setup_reference)
		except TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		except razorpay.errors.BadRequestError as e:
			if is_missing_id(e):
				return {}
			raise GatewayError(str(e)) from e
		payment = next((p for p in payments if is_token_authorisation(p)), None)
		if not payment:
			return {}
		return {
			"payment_method": payment["token_id"],
			"customer": payment.get("customer_id"),
			"payment": payment,
		}

	def remove_saved_method(self, method_id: str, customer_reference: str | None = None) -> None:
		"""Cancel the recurring token. A token already cancelled or gone counts as removed."""
		try:
			self.cancel_mandate(method_id, customer_reference=customer_reference)
		except razorpay.errors.BadRequestError as e:
			if not (is_missing_id(e) or is_already_cancelled(e)):
				raise


def is_token_authorisation(payment: dict) -> bool:
	# A refunded setup payment still left its token, which a retried release must remove.
	return payment.get("status") in ("authorized", "captured", "refunded") and bool(payment.get("token_id"))


def is_missing_id(error: razorpay.errors.BadRequestError) -> bool:
	"""True when Razorpay has no object with the id asked for. The SDK keeps only the
	error description, which reads "The id provided does not exist"."""
	return "does not exist" in str(error).lower()


def is_already_cancelled(error: razorpay.errors.BadRequestError) -> bool:
	"""True when Razorpay refuses to cancel a token because it is no longer live. The SDK
	keeps only the error description."""
	message = str(error).lower()
	return "already" in message and ("cancel" in message or "deleted" in message)


def order_payments(client, order_id: str) -> list[dict]:
	return (client.order.payments(order_id) or {}).get("items") or []
