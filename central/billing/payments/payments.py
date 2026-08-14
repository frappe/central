# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
r"""Card Payment Method lifecycle (issue #05).

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
from frappe import _
from frappe.model.document import Document

from central.billing.states import transition

CARD_METHOD = "Card"


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def gateway_customer_info(team: str) -> "frappe._dict":
	"""Customer details for the gateway, sourced from the team's Billing Profile
	(name, email, phone) — NOT the Team doc, which carries no phone. The keys
	mirror what the adapters read off a Team-like object (`name` / `owner_user` /
	`phone`), so create_customer needs no change. Phone matters: Razorpay rejects a
	recurring order whose customer has no contact."""
	p = (
		frappe.db.get_value("Billing Profile", team, ["legal_name", "email", "phone"], as_dict=True)
		or frappe._dict()
	)
	return frappe._dict(
		name=p.legal_name or team,
		owner_user=p.email or frappe.db.get_value("Team", team, "owner_user"),
		phone=p.phone,
	)


def ensure_gateway_customer(team: str, gateway: str, adapter, customer_id: str | None = None) -> str:
	"""A gateway customer id for the team — every recurring / off-session setup
	needs one. Razorpay rejects an order carrying a `token` without a customer;
	Stripe can save a card under an off-session SetupIntent but then can't charge
	it off-session unless it's attached to a customer.

	The id is stored per (team, gateway) in a Gateway Customer row and **committed
	the instant the customer is minted, before the order/SetupIntent that follows**.
	So if that later step fails (or the request rolls back) the customer is never
	orphaned and the next attempt reuses it — no gateway "fail/return existing"
	flag needed. A team can hold one row per gateway (multi-gateway fallback).
	"""
	if customer_id:
		return customer_id

	existing = frappe.db.get_value(
		"Gateway Customer", {"team": team, "gateway": gateway}, "gateway_customer_id"
	)
	if existing:
		return existing

	cid = adapter.create_customer(gateway_customer_info(team))  # external side-effect
	try:
		frappe.get_doc(
			{
				"doctype": "Gateway Customer",
				"team": team,
				"gateway": gateway,
				"adapter_key": frappe.db.get_value("Payment Gateway", gateway, "adapter_key"),
				"gateway_customer_id": cid,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# A concurrent setup minted+stored one first — use the stored id (and let
		# the just-created duplicate at the gateway lie idle; harmless).
		return frappe.db.get_value(
			"Gateway Customer", {"team": team, "gateway": gateway}, "gateway_customer_id"
		)

	# Persist immediately so a failure in the rest of the request can't lose the id
	# (skipped under tests, where the row stays visible within the test transaction).
	if not frappe.in_test:
		frappe.db.commit()
	return cid


def initiate_payment_method_setup(team: str, gateway: str, gateway_customer_id: str | None = None) -> dict:
	"""Begin adding a card: open a SetupIntent and a pending Payment Method.

	Returns the client secret the frontend confirms the card against. No money
	moves here and the method is not yet usable.
	"""
	_discard_abandoned_setups(team, gateway)
	adapter = _adapter(gateway)
	gateway_customer_id = ensure_gateway_customer(team, gateway, adapter, gateway_customer_id)
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	ceiling = mandate_ceiling(team, gateway, currency)
	handles = adapter.setup_payment_method(
		team,
		{"customer_id": gateway_customer_id, "currency": currency, "max_amount": ceiling},
	)

	method = frappe.get_doc(
		{
			"doctype": "Payment Method",
			"team": team,
			"gateway": gateway,
			"method_type": CARD_METHOD,
			"status": "Pending Validation",
			"gateway_customer_id": gateway_customer_id,
			"setup_reference": handles.get("setup_intent_id"),
			"mandate_max_amount": ceiling,
			"mandate_currency": currency if ceiling else None,
		}
	).insert(ignore_permissions=True)

	return {**handles, "payment_method": method.name}


def mandate_ceiling(team: str, gateway: str, currency: str | None) -> float | None:
	"""What a card mandate in this currency is registered for, or None where the
	rail needs no mandate.

	The customer authenticates once against this number and the bank enforces it,
	so it is the same ceiling the charge path checks: the regulatory limit on the
	rail, held down by the team's trust tier where the tier is lower. Registering
	anything higher would consent the customer to more than we may ever take.
	"""
	from central.billing.gateways import capabilities
	from central.billing.payments import mandates

	if not currency:
		return None
	ceiling = capabilities.silent_charge_ceiling(gateway, currency)
	if ceiling is None:
		return None
	cap = frappe.utils.flt(mandates.team_cap(team))
	return float(min(ceiling, cap)) if cap else float(ceiling)


def _discard_abandoned_setups(team: str, gateway: str):
	"""Delete the team's never-confirmed card setups on this gateway before a fresh
	attempt. A Pending Validation method with no gateway_method_id is an abandoned
	SetupIntent (dialog closed before confirm) — otherwise these pile up in the
	store. Confirmed methods (any status) are left alone."""
	for name in frappe.get_all(
		"Payment Method",
		filters={
			"team": team,
			"gateway": gateway,
			"status": "Pending Validation",
			"gateway_method_id": ["in", [None, ""]],
		},
		pluck="name",
	):
		frappe.delete_doc("Payment Method", name, ignore_permissions=True, force=True)


def confirm_payment_method(
	payment_method: str,
	gateway_method_id: str,
	display_label: str | None = None,
	expiry_month: int | None = None,
	expiry_year: int | None = None,
	gateway_customer_id: str | None = None,
	gateway_mandate_id: str | None = None,
	card_network: str | None = None,
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
	if gateway_mandate_id:
		method.gateway_mandate_id = gateway_mandate_id
	if card_network:
		# What the gateway reported the card to be. We never read the number ourselves.
		method.card_network = card_network.title()
	if display_label:
		method.display_label = display_label
	if expiry_month:
		method.expiry_month = expiry_month
	if expiry_year:
		method.expiry_year = expiry_year
	method.save(ignore_permissions=True)

	if not _adapter(method.gateway).validate_payment_method(method):
		transition(method, "Failed", actor=frappe.session.user, reason="validation failed")
		method.save(ignore_permissions=True)
		return method

	transition(method, "Active", actor=frappe.session.user)
	method.validated_at = frappe.utils.now_datetime()
	method.save(ignore_permissions=True)
	densify_priorities(method.team)
	method.reload()  # pick up priority / is_default set by densify
	return method


def densify_priorities(team: str):
	"""Renumber a team's **active** methods into dense `priority` (0,1,2,…) by
	current order and mirror `is_default` = (priority == 0). The single place that
	defines the charge fallback order; idempotent.

	Only Active methods belong in the order — they're the ones billing charges
	(see collection.ordered_methods). A method still validating (Pending
	Validation) or that failed must never rank or be the default, so non-active
	methods are pushed past the active ones with `is_default` cleared."""
	active = frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": "Active"},
		order_by="priority asc, creation asc",
		pluck="name",
	)
	for i, name in enumerate(active):
		frappe.db.set_value(
			"Payment Method",
			name,
			{"priority": i, "is_default": 1 if i == 0 else 0},
			update_modified=False,
		)
	# Demote everything that isn't active so it can't sit in the fallback order or
	# masquerade as the primary; park its priority after the active tail.
	non_active = frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": ["not in", ["Active", "Cancelled"]]},
		order_by="creation asc",
		pluck="name",
	)
	for j, name in enumerate(non_active):
		frappe.db.set_value(
			"Payment Method",
			name,
			{"priority": len(active) + j, "is_default": 0},
			update_modified=False,
		)


def set_default_payment_method(payment_method: str) -> Document:
	"""Make this the team's primary (priority 0). Only an active method can be."""
	method = frappe.get_doc("Payment Method", payment_method)
	if method.status != "Active":
		frappe.throw(_("Only an active payment method can be the primary."), frappe.ValidationError)
	# Sort it ahead of everyone, then re-densify resolves the rest.
	frappe.db.set_value("Payment Method", method.name, "priority", -1, update_modified=False)
	densify_priorities(method.team)
	return frappe.get_doc("Payment Method", method.name)


def reorder_payment_methods(team: str, ordered: list | str) -> dict:
	"""Set the fallback order from a top-first list of method names."""
	if isinstance(ordered, str):
		ordered = frappe.parse_json(ordered)
	for i, name in enumerate(ordered):
		if frappe.db.get_value("Payment Method", name, "team") != team:
			frappe.throw(_("Method does not belong to this team."), frappe.ValidationError)
		frappe.db.set_value("Payment Method", name, "priority", i, update_modified=False)
	densify_priorities(team)
	return {"team": team, "ordered": ordered}


def delete_payment_method(payment_method: str) -> dict:
	"""Remove a payment method and re-densify so the team keeps a dense, primary-
	first order (or none if it was the last).

	A mandate is revoked at the gateway FIRST. Deleting only our row would leave a
	standing debit permission alive at the bank while the customer believes they
	have withdrawn it — the one failure here that costs them money rather than
	convenience. If the gateway refuses the revoke we keep the row, so the method
	the customer can still see is the one the bank still honours.
	"""
	from central.billing.payments import mandates

	method = frappe.get_doc("Payment Method", payment_method)
	team = method.team
	revoked = False
	if method.method_type == mandates.MANDATE_METHOD and method.gateway_method_id:
		mandates.cancel_mandate(payment_method)
		revoked = True
	frappe.delete_doc("Payment Method", method.name, ignore_permissions=True)
	densify_priorities(team)
	new_default = frappe.db.get_value(
		"Payment Method", {"team": team, "priority": 0, "status": "Active"}, "name"
	)
	return {"deleted": payment_method, "new_default": new_default, "mandate_revoked": revoked}


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
			md = frappe.get_doc("Payment Method", m.name)
			transition(md, "Expired", actor="scheduler", reason="card expiry date passed")
			md.save(ignore_permissions=True)
			expired.append(m.name)
			notifications.notify(
				m.team,
				"Card Expiry",
				context={"label": m.display_label or "Card"},
				reference_doctype="Payment Method",
				reference_name=m.name,
			)
	return {"expired": expired}
