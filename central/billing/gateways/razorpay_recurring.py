# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.gateways.base import PaymentResult
from central.billing.payments.decline import REQUEST_REFUSED

# Razorpay notifies the payer a day before a recurring debit and takes the money after,
# so a debit stays in progress this long before anyone should ask about it.
RECURRING_HOLD_HOURS = 36


def recurring_charge(invoice, payment_method, order_id: str, payer: dict) -> dict:
	"""The createRecurring body. Razorpay refuses a recurring payment without the
	payer's email and contact, even when the customer already holds them."""
	return {
		"amount": round((invoice.amount or 0) * 100),
		"currency": (invoice.currency or "").upper(),
		"order_id": order_id,
		"customer_id": invoice.get("customer_id"),
		"token": payment_method.gateway_method_id,
		"recurring": "1",
		"email": payer.email,
		"contact": payer.phone,
	}


def recurring_result(payment: dict) -> PaymentResult:
	"""What a recurring payment's own status means for the attempt. A UPI or e-mandate debit is
	asynchronous, so until the bank moves the money the attempt is held, not failed: nothing
	charges again and the `payment.captured` webhook settles it."""
	status = payment.get("status")
	known = {"gateway_transaction_id": payment.get("id"), "raw": dict(payment)}
	if status == "captured":
		return PaymentResult(success=True, status="Captured", **known)
	if status == "failed":
		return PaymentResult(
			success=False,
			status="Failed",
			failure_code=payment.get("error_code"),
			decline_code=payment.get("error_reason"),
			failure_reason=payment.get("error_description"),
			**known,
		)
	hold = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=RECURRING_HOLD_HOURS)
	return PaymentResult(success=False, status=status, hold_until=str(hold), **known)


def refused(reason: str) -> PaymentResult:
	"""A recurring debit Razorpay would not create. Nothing was taken."""
	return PaymentResult(
		success=False,
		status="Failed",
		failure_code=REQUEST_REFUSED,
		failure_reason=reason,
		raw={"description": reason},
	)
