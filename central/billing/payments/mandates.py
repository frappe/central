# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""UPI Autopay mandate lifecycle (issue #08).

A mandate's ceiling is structurally tied to the team's trust-tier cap: the
mandate is authorised with `max_amount` = the current cap, so a bill can never
exceed it. A tier promotion that raises the cap requires customer re-consent
(re-authorisation); until then the team is held at the old ceiling. Cards are
exempt (off-session, any amount), so only `upi_autopay` methods participate.

This module never imports a gateway SDK directly — it resolves an adapter
through the registry, keeping the gateway seam intact (see gateways/base.py).
"""

import frappe
from frappe import _

from central.billing.doctype.billing_profile.billing_profile import normalize_phone
from central.billing.payments.decline import ORDER_MISMATCH, PAYMENT_NOT_AUTHORISED, SIGNATURE_INVALID
from central.billing.states import transition

MANDATE_METHOD = "UPI Autopay"
CARD_METHOD = "Card"

# UPI Autopay recurring ceiling (merchant-category-code limit): a recurring UPI
# payment for this MCC cannot exceed Rs. 1,00,000. Above this the mandate would
# fail at charge time, so we block UPI setup and steer the team to a card.
UPI_RECURRING_MAX = 100000

# Razorpay recurring-card token ceiling — cards are exempt from the UPI MCC limit,
# but Razorpay still caps a token's max_amount at Rs. 10,00,000 (100,000,000 paise,
# the value the adapter multiplies up to). Going above it makes order.create reject
# the mandate with "The max amount may not be greater than 100000000".
CARD_TOKEN_MAX = 1000000


def team_cap(team: str):
	"""Current trust-tier monthly cap for a team (0 when no tier exists yet)."""
	from central.billing.catalog.entitlements import get_team_caps

	return get_team_caps(team).max_spend or 0


def last_invoice_amount(team: str):
	"""Most recent invoice total for the team (0 when none) — used to predict
	whether a recurring charge would breach the UPI limit."""
	rows = frappe.get_all(
		"Invoice", filters={"team": team}, fields=["total"], order_by="creation desc", limit=1
	)
	return frappe.utils.flt(rows[0].total) if rows else 0.0


def upi_eligibility(team: str) -> dict:
	"""Whether UPI Autopay is usable for a team, given the Rs. 1,00,000 recurring
	limit. Blocked when the trust-tier cap or the last invoice would breach it."""
	cap = frappe.utils.flt(team_cap(team))
	last = last_invoice_amount(team)
	reason = None
	if cap >= UPI_RECURRING_MAX:
		reason = (
			f"Your spend cap (₹{cap:,.0f}) is at or above the ₹{UPI_RECURRING_MAX:,.0f} "
			"UPI Autopay recurring limit — set up a card instead."
		)
	elif last >= UPI_RECURRING_MAX:
		reason = (
			f"Your last invoice (₹{last:,.0f}) is at or above the ₹{UPI_RECURRING_MAX:,.0f} "
			"UPI Autopay recurring limit — set up a card instead."
		)
	return {
		"eligible": reason is None,
		"reason": reason,
		"cap": cap,
		"last_invoice": last,
		"limit": UPI_RECURRING_MAX,
	}


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def _prefill(team: str) -> dict:
	"""Contact details to pre-populate the Razorpay Checkout sheet so the customer
	isn't re-asked for the name/email/phone we already hold. Razorpay does NOT
	auto-fill these from `customer_id` in recurring mode, so Checkout must be handed
	an explicit `prefill` block. Only non-empty values are included."""
	p = (
		frappe.db.get_value("Billing Profile", team, ["legal_name", "email", "phone"], as_dict=True)
		or frappe._dict()
	)
	out = {}
	if p.legal_name:
		out["name"] = p.legal_name
	if p.email:
		out["email"] = p.email
	if p.phone:
		out["contact"] = p.phone
	return out


def _ensure_customer(team: str, gateway: str, adapter, customer_id: str | None = None) -> str:
	"""Reuse-or-create a gateway customer for a mandate setup. Recurring orders
	need a customer (see payments.ensure_gateway_customer for the why); shared so
	the card-lifecycle (#05) and mandate (#08) paths provision identically."""
	from central.billing.payments import payments

	return payments.ensure_gateway_customer(team, gateway, adapter, customer_id)


def _require_card_contact(
	team: str, gateway: str, adapter, customer_id: str, contact: str | None = None
) -> str:
	"""Ensure the customer for a Razorpay *card* mandate carries a contact (phone) —
	without it Razorpay errors "The contact field is required for recurring links".
	(UPI Autopay does not need one, so this is only called from the card path.)
	Returns the customer id to use for the order, which may differ from the input
	(see the collision case below).

	The phone is optional on the billing profile, so the dashboard collects it inline
	at card setup when missing and passes it here. Use the inline `contact` else the
	profile's phone; persist an inline one back to the profile (asked once); sync
	name/email/contact onto the (possibly reused / older, contactless) customer.
	"""
	if frappe.db.get_value("Payment Gateway", gateway, "adapter_key") != "Razorpay":
		return customer_id
	p = (
		frappe.db.get_value(
			"Billing Profile", team, ["legal_name", "email", "phone", "country"], as_dict=True
		)
		or frappe._dict()
	)
	contact = str(contact or "").strip()
	# An inline phone is held to the same rule as one entered on the profile.
	if contact:
		contact = normalize_phone(contact, p.country)
	phone = contact or str(p.phone or "").strip()
	if not phone:
		frappe.throw(
			_("A phone number is required to set up automatic payments on this card."),
			frappe.ValidationError,
		)
	# An inline-provided phone is saved to the profile so it's collected only once.
	# Saved BEFORE the recovery path so gateway_customer_info() below carries it.
	if contact and contact != str(p.phone or ""):
		frappe.db.set_value("Billing Profile", team, "phone", contact)

	try:
		adapter.update_customer(
			customer_id, {"name": p.legal_name or team, "email": p.email, "contact": phone}
		)
		return customer_id
	except Exception as e:
		# Razorpay enforces (email, contact) uniqueness per merchant. If a different
		# customer already owns this identity (e.g. our stored customer was minted
		# contactless and the real one already carries the phone), the edit fails
		# "Customer already exists for the merchant". Swallowing it would leave a
		# contactless customer and the order would then fail "contact required".
		# Instead, fetch the customer that already has (email, contact) — create with
		# fail_existing returns it now that the phone is on the profile — and repoint
		# our stored row so the recurring order uses the contact-bearing customer.
		if "already exists" not in str(e).lower():
			raise
		from central.billing.payments.payments import gateway_customer_info

		corrected = adapter.create_customer(gateway_customer_info(team))
		if corrected and corrected != customer_id:
			frappe.db.set_value(
				"Gateway Customer",
				{"team": team, "gateway": gateway},
				"gateway_customer_id",
				corrected,
			)
			return corrected
		return customer_id


def setup_mandate(team: str, gateway: str, customer_id: str | None = None, is_default: int = 0) -> dict:
	"""Begin UPI Autopay authorisation.

	The ceiling is locked to the team's current trust-tier cap. Refuses when the
	team is above the UPI recurring limit (cap or last invoice >= Rs. 1,00,000) —
	the UI hides UPI in that case, this is the server-side backstop. Returns the
	client-side handles the UI runs Razorpay Checkout against, plus the name of
	the (pending) Payment Method. No money is moved and no token exists yet.
	"""
	elig = upi_eligibility(team)
	if not elig["eligible"]:
		frappe.throw(elig["reason"], frappe.ValidationError)

	cap = team_cap(team)
	adapter = _adapter(gateway)
	customer_id = _ensure_customer(team, gateway, adapter, customer_id)
	# UPI Autopay carries no customer contact — no phone needed here.
	handles = adapter.setup_payment_method(
		team, {"method": "upi", "max_amount": cap, "customer_id": customer_id}
	)

	method = frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": gateway,
			"method_type": MANDATE_METHOD,
			"status": "Pending Validation",
			"card_network": "UPI",
			"mandate_max_amount": cap,
			"mandate_currency": "INR",
			"gateway_customer_id": customer_id,
			"setup_reference": handles.get("order_id"),
			"is_default": is_default,
		}
	).insert(ignore_permissions=True)

	return {**handles, "payment_method": method.name, "prefill": _prefill(team)}


def setup_card(
	team: str,
	gateway: str,
	customer_id: str | None = None,
	contact: str | None = None,
	fallback_reason: str | None = None,
) -> dict:
	"""Begin a Razorpay recurring-card authorisation (no UPI MCC limit).

	Same Checkout → token → recurring-charge machinery as a UPI mandate, but on
	the card rail. A Razorpay card mandate needs the customer to have a contact;
	`contact` is the phone the dashboard collects inline when the profile has none.
	Returns the client-side handles plus the pending Payment Method name.
	"""
	adapter = _adapter(gateway)
	customer_id = _ensure_customer(team, gateway, adapter, customer_id)
	# May return a different (contact-bearing) customer if the held one collided.
	customer_id = _require_card_contact(team, gateway, adapter, customer_id, contact=contact)
	handles = adapter.setup_payment_method(
		team, {"method": "card", "max_amount": CARD_TOKEN_MAX, "customer_id": customer_id}
	)

	method = frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": gateway,
			"method_type": CARD_METHOD,
			"status": "Pending Validation",
			"mandate_currency": "INR",
			"gateway_customer_id": customer_id,
			"fallback_reason": fallback_reason,
			"card_network": "RuPay" if fallback_reason == "Rupay" else None,
			"setup_reference": handles.get("order_id"),
		}
	).insert(ignore_permissions=True)

	# _require_card_contact has already persisted any inline phone onto the profile,
	# so _prefill picks it up here.
	return {**handles, "payment_method": method.name, "prefill": _prefill(team)}


def confirm_mandate(payment_method: str, callback: dict):
	"""Confirm the Razorpay Checkout callback that authorised the mandate.

	1. The checkout-callback signature must be valid (it binds the order and payment ids).
	2. The callback's order must be the authorisation order Central opened for this method.
	3. The payment, read from Razorpay, must belong to that order and this method's
	   customer, and must be authorised or captured. The token is read from it, never
	   taken from the browser.
	A new active mandate retires any sibling active mandate for the same team+gateway
	(the re-authorisation case), so the higher ceiling cleanly supersedes.
	A method already past validation is returned as it is, so a repeated callback
	neither activates a refused mandate nor refunds an authorisation twice.
	"""
	method = frappe.get_doc("Payment Method", payment_method)
	if method.status != "Pending Validation":
		return method
	adapter = _adapter(method.gateway)

	if not adapter.verify_payment_signature(callback):
		return _refuse_mandate(method, SIGNATURE_INVALID, "The checkout signature is invalid.")
	if not method.setup_reference or callback.get("razorpay_order_id") != method.setup_reference:
		return _refuse_mandate(method, ORDER_MISMATCH, "The callback is for another order.")
	payment = adapter.get_payment(callback.get("razorpay_payment_id"))
	if not _is_mandate_payment(method, payment):
		return _refuse_mandate(method, PAYMENT_NOT_AUTHORISED, "The payment does not authorise this mandate.")

	method.gateway_method_id = payment["token_id"]
	method.display_label = _mandate_label(method, payment)
	transition(method, "Active", actor=frappe.session.user)
	method.validated_at = frappe.utils.now_datetime()
	method.reauth_required = 0
	method.save(ignore_permissions=True)

	# A re-authorised UPI mandate supersedes the old one; cards coexist as backups
	# (the fallback list, #28), so only retire siblings for UPI mandates.
	if method.method_type == MANDATE_METHOD:
		_retire_superseded_mandates(method)

	from central.billing.payments import payments

	payments.densify_priorities(method.team)  # slot the new method into the fallback order
	_queue_authorisation_refund(method, payment)
	method.reload()
	return method


def _queue_authorisation_refund(method, payment: dict) -> None:
	"""Queue the refund of the authorisation payment. It registers the mandate and pays no bill."""
	if payment.get("status") != "captured":
		return

	frappe.enqueue(
		"central.billing.payments.mandates.refund_authorisation_payment",
		payment_method=method.name,
		payment_id=payment["id"],
		amount=frappe.utils.flt(payment.get("amount")) / 100,
		job_id=f"mandate-authorisation-refund::{payment['id']}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def refund_authorisation_payment(payment_method: str, payment_id: str, amount: float) -> None:
	"""Refund the authorisation payment that registered a mandate.

	1. The refund is keyed on the payment, so a retried job never refunds twice.
	2. A failure leaves a comment on the method for an operator and fails the job.
	   The mandate stays active either way.
	"""
	method = frappe.get_doc("Payment Method", payment_method)
	try:
		result = _adapter(method.gateway).refund(
			frappe._dict(gateway_transaction_id=payment_id),
			amount,
			reason="Mandate authorisation",
			idempotency_key=f"mandate-authorisation-{payment_id}",
		)
		if not result.success:
			raise frappe.ValidationError(f"Gateway refund status: {result.status}")
	except Exception as error:
		method.add_comment(
			"Comment", f"Authorisation payment {payment_id} ({amount} INR) was not refunded: {error}"
		)
		# The job's own rollback would drop the comment the operator needs.
		frappe.db.commit()
		raise


def _is_mandate_payment(method, payment: dict) -> bool:
	"""Whether the payment is an authorisation on this method's order and customer, with a token."""
	return (
		payment.get("order_id") == method.setup_reference
		and payment.get("status") in ("authorized", "captured")
		and bool(payment.get("token_id"))
		and (not method.gateway_customer_id or payment.get("customer_id") == method.gateway_customer_id)
	)


def _mandate_label(method, payment: dict) -> str:
	"""How the customer recognises the mandate: the UPI ID, or the card's network and last four digits."""
	card = payment.get("card") or {}
	if card.get("last4"):
		return f"{card.get('network') or 'Card'} ···· {card['last4']}"
	if payment.get("vpa"):
		return f"{method.method_type} · {payment['vpa']}"
	return method.method_type


def _refuse_mandate(method, failure_code: str, reason: str):
	"""Fail the method and return it. It does not raise, so the failure is not rolled back."""
	method.record_failure({"failure_code": failure_code, "failure_reason": reason})
	transition(method, "Failed", actor=frappe.session.user, reason=failure_code)
	# Only billing code changes a method's status; the caller checked billing:manage.
	method.save(ignore_permissions=True)
	return method


def cancel_mandate(payment_method: str):
	"""Revoke the UPI Autopay token at the gateway and mark the method cancelled."""
	method = frappe.get_doc("Payment Method", payment_method)
	if method.gateway_method_id:
		_adapter(method.gateway).cancel_mandate(
			method.gateway_method_id, customer_reference=method.gateway_customer_id
		)
	transition(method, "Cancelled", actor=frappe.session.user, reason="mandate revoked")
	method.save(ignore_permissions=True)
	return method


def reauthorise_mandate(payment_method: str) -> dict:
	"""Start a fresh authorisation at the team's current (raised) cap.

	The existing mandate stays active at its old ceiling until the new one is
	confirmed — the customer is never left without a working mandate.
	"""
	method = frappe.get_doc("Payment Method", payment_method)
	return setup_mandate(method.team, method.gateway, customer_id=method.gateway_customer_id)


# --- cap reconciliation -----------------------------------------------------


def active_mandate_ceiling(team: str):
	"""Highest ceiling among a team's active mandates (None if none active)."""
	ceilings = frappe.get_all(
		"Payment Method",
		filters={"team": team, "method_type": MANDATE_METHOD, "status": "Active"},
		pluck="mandate_max_amount",
	)
	return max(ceilings) if ceilings else None


def effective_cap(team: str):
	"""The cap a mandate team is actually held to: min(tier cap, mandate ceiling).

	A team with no active mandate is bounded purely by its tier cap. A pending
	re-authorisation keeps the ceiling at the *old* value even after the tier
	cap rises, so this naturally returns the old ceiling until re-consent.
	"""
	cap = team_cap(team)
	ceiling = active_mandate_ceiling(team)
	return cap if ceiling is None else min(cap, ceiling)


def reauth_pending(team: str) -> bool:
	"""True if any active mandate is awaiting customer re-authorisation."""
	return bool(
		frappe.get_all(
			"Payment Method",
			filters={
				"team": team,
				"method_type": MANDATE_METHOD,
				"status": "Active",
				"reauth_required": 1,
			},
			limit=1,
		)
	)


def reconcile_mandates_to_cap(team: str):
	"""After a tier change, flag/clear re-authorisation on active mandates.

	An active mandate whose ceiling is below the new cap needs re-consent (the
	team is functionally held at the old ceiling until then). A mandate whose
	ceiling already covers the cap — e.g. after a demotion — is cleared.
	Returns the list of mandates newly requiring re-authorisation.
	"""
	cap = team_cap(team)
	flagged = []
	for method in frappe.get_all(
		"Payment Method",
		filters={"team": team, "method_type": MANDATE_METHOD, "status": "Active"},
		fields=["name", "mandate_max_amount"],
	):
		needs = cap > (method.mandate_max_amount or 0)
		frappe.db.set_value("Payment Method", method.name, "reauth_required", 1 if needs else 0)
		if needs:
			flagged.append(method.name)
	return flagged


def _retire_superseded_mandates(new_method):
	"""Cancel older active mandates for the same team+gateway once a new mandate
	(typically a re-authorisation at a higher ceiling) goes active."""
	siblings = frappe.get_all(
		"Payment Method",
		filters={
			"team": new_method.team,
			"gateway": new_method.gateway,
			"method_type": MANDATE_METHOD,
			"status": "Active",
			"name": ["!=", new_method.name],
		},
		pluck="name",
	)
	for name in siblings:
		cancel_mandate(name)


# --- mandate lifecycle from the gateway -------------------------------------

# Stripe reports a mandate that can no longer be debited as `inactive`; Razorpay
# calls the same thing a cancelled/revoked token. Either way the customer's
# standing permission is gone and the method cannot be charged off-session.
_DEAD_MANDATE_STATUSES = ("inactive", "cancelled", "canceled", "revoked", "expired")


def _payment_method_for_mandate(mandate_id: str) -> dict | None:
	"""The Payment Method a gateway's mandate id refers to. Stripe keeps it in
	gateway_mandate_id; Razorpay has no separate mandate id and reuses the recurring
	token, gateway_method_id, for the same purpose."""
	method = frappe.qb.DocType("Payment Method")
	row = (
		frappe.qb.from_(method)
		.select(method.name, method.team)
		.where((method.gateway_mandate_id == mandate_id) | (method.gateway_method_id == mandate_id))
		.limit(1)
		.run(as_dict=True)
	)
	return row[0] if row else None


def apply_mandate_event(event_name: str) -> dict:
	"""Mark the Payment Method a gateway mandate event refers to.

	A revoked mandate is not a failed charge — nothing was attempted — but it does
	mean the next one cannot run. So the method drops out of the charge order and
	the team is put in front of the same choice a failed registration gives them,
	rather than discovering it when an invoice quietly goes unpaid.
	"""
	from central.billing.payments import charges, collection_mode

	event = frappe.get_doc("Webhook Event", event_name)
	payload = frappe.parse_json(event.raw_payload) if event.raw_payload else {}
	mandate = ((payload.get("data") or {}).get("object")) or {}
	mandate_id = mandate.get("id")
	status = (mandate.get("status") or "").lower()

	method = _payment_method_for_mandate(mandate_id) if mandate_id else None
	if not method:
		charges._mark_event(event, "Ignored")
		return {"handled": False, "reason": "no_method_for_mandate"}
	event.payment_method = method.name
	if status not in _DEAD_MANDATE_STATUSES:
		charges._mark_event(event, "Processed")
		return {"handled": True, "result": "mandate_still_live", "payment_method": method.name}

	doc = frappe.get_doc("Payment Method", method.name)
	transition(doc, "Cancelled", actor="webhook", reason="mandate revoked at the gateway")
	doc.reauth_required = 1
	doc.save(ignore_permissions=True)
	collection_mode.trip(method.team, "mandate_failed")
	charges._mark_event(event, "Processed")
	return {"handled": True, "result": "mandate_revoked", "payment_method": method.name}
