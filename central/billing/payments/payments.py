# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Card Payment Method lifecycle (issue #05).

Adding a card is a two-step, gateway-mediated flow: the customer initiates
setup (Stripe SetupIntent -> client secret), confirms with the card on the
frontend, and the method is proven live by a **micro-charge captured and
immediately refunded** before it becomes `active`. A method is never trusted on
the API response alone.

    pending_validation --(micro-charge ok)--> active --(monthly expiry)--> expired
                       \--(micro-charge fail)--> failed

Cards are off-session and have no mandate ceiling (that is the UPI Autopay path,
see mandates.py). This module never imports a gateway SDK — it resolves the
adapter through the registry, keeping the gateway seam intact.
"""

import frappe
from frappe.model.document import Document

CARD_METHOD = "Card"


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def ensure_gateway_customer(team: str, gateway: str, adapter, customer_id: str | None = None) -> str:
	"""A gateway customer id for the team — every recurring / off-session setup
	needs one. Razorpay rejects an order carrying a `token` without a customer
	("Customer Id is required with token field"); Stripe can save a card under an
	off-session SetupIntent but then can't charge it off-session unless it's
	attached to a customer. Reuse a customer already minted for this team+gateway
	so a fresh one isn't created on every attempt; otherwise create one through
	the adapter, keeping the gateway SDK behind the seam.
	"""
	if customer_id:
		return customer_id
	existing = frappe.db.get_value(
		"Payment Method",
		{"team": team, "gateway": gateway, "gateway_customer_id": ["is", "set"]},
		"gateway_customer_id",
	)
	if existing:
		return existing
	return adapter.create_customer(frappe.get_doc("Team", team))


@frappe.whitelist()
def initiate_payment_method_setup(team: str, gateway: str, gateway_customer_id: str | None = None) -> dict:
	"""Begin adding a card: open a SetupIntent and a pending Payment Method.

	Returns the client secret the frontend confirms the card against. No money
	moves here and the method is not yet usable.
	"""
	adapter = _adapter(gateway)
	gateway_customer_id = ensure_gateway_customer(team, gateway, adapter, gateway_customer_id)
	handles = adapter.setup_payment_method(team, {"customer_id": gateway_customer_id})

	method = frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": gateway,
			"method_type": CARD_METHOD,
			"status": "Pending Validation",
			"gateway_customer_id": gateway_customer_id,
			"setup_reference": handles.get("setup_intent_id"),
		}
	).insert(ignore_permissions=True)

	return {**handles, "payment_method": method.name}


@frappe.whitelist()
def confirm_payment_method(
	payment_method: str,
	gateway_method_id: str,
	display_label: str | None = None,
	expiry_month: int | None = None,
	expiry_year: int | None = None,
	gateway_customer_id: str | None = None,
) -> dict:
	"""Confirm a card the customer authorised on the frontend.

	Stores the gateway method handle, then runs the micro-charge + auto-refund
	validation. The method becomes `active` only on a successful micro-charge;
	a failure (or decline) leaves it `failed`. The first active method for a
	team becomes its default.
	"""
	method = frappe.get_doc("Payment Method", payment_method)
	method.gateway_method_id = gateway_method_id
	if gateway_customer_id:
		method.gateway_customer_id = gateway_customer_id
	if display_label:
		method.display_label = display_label
	if expiry_month:
		method.expiry_month = expiry_month
	if expiry_year:
		method.expiry_year = expiry_year
	method.save(ignore_permissions=True)

	if not _adapter(method.gateway).validate_payment_method(method):
		method.status = "Failed"
		method.save(ignore_permissions=True)
		return method

	method.status = "Active"
	method.validated_at = frappe.utils.now_datetime()
	method.save(ignore_permissions=True)
	densify_priorities(method.team)
	method.reload()  # pick up priority / is_default set by densify
	return method


def densify_priorities(team: str):
	"""Renumber a team's methods into dense `priority` (0,1,2,…) by current order
	and mirror `is_default` = (priority == 0). The single place that defines the
	fallback order; idempotent."""
	names = frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": ["!=", "Cancelled"]},
		order_by="priority asc, creation asc",
		pluck="name",
	)
	for i, name in enumerate(names):
		frappe.db.set_value(
			"Payment Method",
			name,
			{"priority": i, "is_default": 1 if i == 0 else 0},
			update_modified=False,
		)


@frappe.whitelist()
def set_default_payment_method(payment_method: str) -> Document:
	"""Make this the team's primary (priority 0). Only an active method can be."""
	method = frappe.get_doc("Payment Method", payment_method)
	if method.status != "Active":
		frappe.throw("Only an active payment method can be the primary.", frappe.ValidationError)
	# Sort it ahead of everyone, then re-densify resolves the rest.
	frappe.db.set_value("Payment Method", method.name, "priority", -1, update_modified=False)
	densify_priorities(method.team)
	return frappe.get_doc("Payment Method", method.name)


@frappe.whitelist()
def reorder_payment_methods(team: str, ordered: list | str) -> dict:
	"""Set the fallback order from a top-first list of method names."""
	if isinstance(ordered, str):
		ordered = frappe.parse_json(ordered)
	for i, name in enumerate(ordered):
		if frappe.db.get_value("Payment Method", name, "team") != team:
			frappe.throw("Method does not belong to this team.", frappe.ValidationError)
		frappe.db.set_value("Payment Method", name, "priority", i, update_modified=False)
	densify_priorities(team)
	return {"team": team, "ordered": ordered}


@frappe.whitelist()
def delete_payment_method(payment_method: str) -> dict:
	"""Remove a payment method and re-densify so the team keeps a dense, primary-
	first order (or none if it was the last)."""
	method = frappe.get_doc("Payment Method", payment_method)
	team = method.team
	frappe.delete_doc("Payment Method", method.name, ignore_permissions=True)
	densify_priorities(team)
	new_default = frappe.db.get_value(
		"Payment Method", {"team": team, "priority": 0, "status": "Active"}, "name"
	)
	return {"deleted": payment_method, "new_default": new_default}


def expire_payment_methods(now=None) -> dict:
	"""Monthly scheduler: flip cards past their expiry month to `expired`.

	A card is valid through the end of its printed expiry month; the day after,
	it is no longer chargeable.
	"""
	from central.billing.platform import notifications

	today = frappe.utils.getdate(now or frappe.utils.now_datetime())
	expired = []
	for m in frappe.get_all(
		"Payment Method",
		filters={"method_type": CARD_METHOD, "status": "Active"},
		fields=["name", "team", "display_label", "expiry_month", "expiry_year"],
	):
		if not m.expiry_year or not m.expiry_month:
			continue
		month_start = frappe.utils.getdate(f"{int(m.expiry_year):04d}-{int(m.expiry_month):02d}-01")
		if frappe.utils.get_last_day(month_start) < today:
			frappe.db.set_value("Payment Method", m.name, "status", "Expired")
			expired.append(m.name)
			notifications.notify(
				m.team, "Card Expiry", context={"label": m.display_label or "Card"},
				reference_doctype="Payment Method", reference_name=m.name,
			)
	return {"expired": expired}
