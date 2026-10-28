# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.gateways.base import VerifiedPayment
from central.billing.payments import decline
from central.billing.states import record_event, transition

DECLINED_EVENT = "Top-up Order Declined"


class PaymentDoesNotCover(frappe.ValidationError):
	"""A payment that does not belong to a top-up or does not cover its total."""


class TopupOrder(Document):
	"""A wallet top-up Central asked a gateway for, stored before the payer acts.

	1. The order is inserted first; its name is the receipt sent to the gateway.
	2. The gateway's order id is recorded the moment the gateway returns it.
	3. A payment credits the wallet only through `credit_wallet`, which checks that the
	   payment belongs to this order and covers its amount and currency.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		credit: DF.Currency
		currency: DF.Link
		decline_code: DF.Data | None
		failed_attempts: DF.Int
		failure_code: DF.Data | None
		failure_reason: DF.SmallText | None
		gateway: DF.Link
		gateway_order_id: DF.Data | None
		gateway_payment_id: DF.Data | None
		gst: DF.Currency
		last_failed_at: DF.Datetime | None
		ledger_entry: DF.Link | None
		status: DF.Literal["Created", "Credited", "Failed", "Expired"]
		team: DF.Link
		total: DF.Currency
	# end: auto-generated types

	@classmethod
	def start(cls, team: str, gateway: str, currency: str, total, credit=None, gst=0) -> "TopupOrder":
		# A system record: customers reach it only through the top-up routes, which check billing:manage.
		return frappe.get_doc(
			{
				"doctype": "Top-up Order",
				"team": team,
				"gateway": gateway,
				"currency": currency,
				"total": total,
				"credit": credit,
				"gst": gst,
			}
		).insert(ignore_permissions=True)

	@classmethod
	def for_payment(cls, payment: VerifiedPayment, gateway: str) -> "TopupOrder | None":
		"""The top-up a gateway payment belongs to: by the order the gateway names, or by
		our own receipt where only we can set it. None for a payment that is not a top-up,
		or for a top-up started on another gateway."""
		name = payment.order_id and frappe.db.get_value(
			"Top-up Order", {"gateway": gateway, "gateway_order_id": payment.order_id}, "name"
		)
		if not name and payment.receipt:
			name = frappe.db.exists("Top-up Order", {"name": payment.receipt, "gateway": gateway})
		return frappe.get_doc("Top-up Order", name) if name else None

	def record_gateway_order(self, gateway_order_id: str) -> None:
		self.db_set("gateway_order_id", gateway_order_id)

	def expire(self) -> None:
		"""Stop asking the gateway about an order nobody paid."""
		transition(self, "Expired", actor="reconciliation", correlation=self.team)
		# Reconciliation runs as the system with no session user to check.
		self.save(ignore_permissions=True)

	def record_decline(self, failure: decline.Failure, gateway_event_id: str) -> None:
		"""Keep why the gateway declined a payment on this order, and log each decline as
		a Billing Event. The order stays open, because the payer can try again on it.

		1. Locked, so two failure webhooks both count.
		2. A gateway event already logged on this order counts once."""
		frappe.db.get_value("Top-up Order", self.name, "name", for_update=True)
		self.reload()
		if self._has_declined_event(gateway_event_id):
			return

		self.failed_attempts = frappe.utils.cint(self.failed_attempts) + 1
		self.last_failed_at = frappe.utils.now_datetime()
		self.update(decline.failure_fields(failure))
		# The webhook runs as the system with no session user to check.
		self.save(ignore_permissions=True)
		record_event(self, DECLINED_EVENT, reason=self.failure_code, correlation=gateway_event_id)

	def _has_declined_event(self, gateway_event_id: str) -> bool:
		return bool(
			frappe.db.exists(
				"Billing Event",
				{
					"subject_doctype": "Top-up Order",
					"subject": self.name,
					"event_type": DECLINED_EVENT,
					"correlation": gateway_event_id,
				},
			)
		)

	def fail(self, reason: str) -> None:
		"""Stop retrying an order an operator has to resolve, and keep the reason on it."""
		transition(self, "Failed", reason=reason, actor="reconciliation", correlation=self.team)
		self.failure_reason = reason
		# Reconciliation runs as the system with no session user to check.
		self.save(ignore_permissions=True)

	def credit_wallet(self, payment: VerifiedPayment) -> dict:
		"""Credit the wallet once for a payment that belongs to this order and covers it.

		Locked, so the confirm callback, the webhook and the reconciler book one credit."""
		from central.billing.revenue import credits

		frappe.db.get_value("Top-up Order", self.name, "name", for_update=True)
		self.reload()
		if self.status == "Credited":
			return {
				"ledger_entry": self.ledger_entry,
				"new_balance": credits.get_balance(self.team)["balance"],
			}
		self._require_covering(payment)

		adapter_key = frappe.db.get_value("Payment Gateway", self.gateway, "adapter_key")
		result = credits.purchase(
			self.team,
			self.total,
			self.currency,
			reference_name=payment.payment_id,
			note=f"Wallet top-up ({payment.payment_id})",
			gateway_payment_id=payment.payment_id,
			gateway=adapter_key,
			credit=self.credit or None,
		)
		self._credit_surplus(payment, adapter_key)
		transition(self, "Credited", actor="gateway", correlation=self.team, amount=self.total)
		self.gateway_payment_id = payment.payment_id
		self.ledger_entry = result["ledger_entry"]
		# A verified gateway payment credits it, often from a Guest webhook.
		self.save(ignore_permissions=True)
		return result

	def _credit_surplus(self, payment: VerifiedPayment, adapter_key: str | None) -> None:
		"""Keep anything paid above the order total as wallet credit, and tell an operator."""
		from central.billing.revenue import credits

		surplus = frappe.utils.flt(frappe.utils.flt(payment.amount) - frappe.utils.flt(self.total), 2)
		if surplus <= 0:
			return

		credits.purchase(
			self.team,
			surplus,
			self.currency,
			reference_name=payment.payment_id,
			note=f"Payment for top-up {self.name} above its total",
			gateway_payment_id=f"{payment.payment_id}:surplus",
			gateway=adapter_key,
		)
		message = f"Payment {payment.payment_id} of {payment.currency} {payment.amount} paid {surplus} above the total; credited to the wallet."
		self.add_comment("Info", message)
		frappe.log_error(title=f"Payment needs review on {self.name}", message=message)

	def _require_covering(self, payment: VerifiedPayment) -> None:
		if payment.order_id != self.gateway_order_id and payment.receipt != self.name:
			self._refuse(_("This payment does not belong to top-up {0}.").format(self.name))
		if not payment.is_enough_for(self.total, self.currency):
			self._refuse(
				_("Payment {0} ({1} {2}) does not cover top-up {3} ({4} {5}).").format(
					payment.payment_id, payment.currency, payment.amount, self.name, self.currency, self.total
				)
			)

	def _refuse(self, reason: str) -> None:
		frappe.log_error(title=f"Top-up {self.name} not credited", message=reason)
		frappe.throw(
			_(
				"The payment could not be confirmed. Check your credit balance and payment history before paying again. Contact support if you were charged but no credit appears."
			),
			PaymentDoesNotCover,
		)


def on_doctype_update() -> None:
	frappe.db.add_index("Top-up Order", ["gateway", "gateway_order_id"])
	frappe.db.add_index("Top-up Order", ["status", "creation"])
