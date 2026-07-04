# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""In-app billing API — a single facade of pilot-authenticated caller methods for a
site/pilot to drive a team's billing.

Every method authenticates via `pilot_credential_auth` (the X-Pilot-Token header → a
Pilot Credential bound to a team) and takes the **team from that credential**, never
a request parameter — so a pilot can only ever act on its own team (IDOR defence).
Record-scoped methods additionally check the record belongs to that team. No business
logic lives here; each method delegates to the existing billing service layer.
"""

import frappe

from central.api.pilot import pilot_credential_auth
from central.billing.api.dashboard._shared import (
	_add_method_gateway,
	_require_billing_setup,
	_team_currency,
)


def _team() -> str:
	"""The team the authenticated pilot credential is bound to (never a request param)."""
	return frappe.local.pilot_credential.team


def _assert_owns(team_of_record: str | None) -> None:
	"""Guard a record-scoped call: the record must belong to the credential's team."""
	if team_of_record != _team():
		frappe.throw("Not permitted for this team.", frappe.PermissionError)


def _asset() -> str:
	"""The asset (server) the authenticated pilot credential is bound to — the default
	target for asset-scoped calls, so the pilot never has to know its own asset id."""
	return frappe.local.pilot_credential.asset


def _money(amount, currency: str) -> str:
	return frappe.utils.fmt_money(frappe.utils.flt(amount), currency=currency)


def _asset_specs(asset_row) -> dict:
	"""The three meter labels from the provisioned VM's live specs."""
	ram_gb = int(round(frappe.utils.flt(asset_row.memory_megabytes) / 1024))
	return {
		"cpu": f"{int(frappe.utils.flt(asset_row.vcpus))} vCPU",
		"memory": f"{ram_gb} GB RAM",
		"storage": f"{int(frappe.utils.flt(asset_row.disk_gigabytes))} GB SSD",
	}


# Plan-include resource types → the three meters (the catalog names its resources
# Compute/Memory/Disk; accept the shorter aliases too).
_METER_GROUP = {"compute": "cpu", "vcpu": "cpu", "cpu": "cpu",
				"memory": "memory", "ram": "memory",
				"disk": "storage", "storage": "storage", "ssd": "storage"}
_METER_SUFFIX = {"cpu": "vCPU", "memory": "GB RAM", "storage": "GB SSD"}


def _specs_from_includes(includes: list[dict]) -> dict:
	"""Meter labels derived from a plan's includes — the fallback for an asset with
	no live specs yet (Pending / not-provisioned)."""
	out = {"cpu": None, "memory": None, "storage": None}
	for item in includes or []:
		key = _METER_GROUP.get((item.get("resource_type") or "").lower())
		if key and not out[key]:
			out[key] = f"{frappe.utils.flt(item.get('quantity')):g} {_METER_SUFFIX[key]}"
	return out


def _resolve_specs(asset_row, plan: str | None) -> dict:
	"""The VM's live specs when known, else the plan's intended specs."""
	if any(frappe.utils.flt(asset_row.get(f)) for f in ("vcpus", "memory_megabytes", "disk_gigabytes")):
		return _asset_specs(asset_row)
	includes = frappe.get_all("Plan Includes", {"parent": plan}, ["resource_type", "quantity", "unit"]) if plan else []
	return _specs_from_includes([dict(row) for row in includes])


def _includes_spec_line(includes: list[dict]) -> str:
	"""'2 vCPU · 4 GB RAM · 40 GB SSD' from a plan's includes (Change-plan rows)."""
	labels = {"vcpu": "vCPU", "cpu": "vCPU", "memory": "GB RAM", "ram": "GB RAM",
			  "disk": "GB SSD", "storage": "GB SSD"}
	parts = []
	for item in includes or []:
		qty = frappe.utils.flt(item.get("quantity"))
		rtype = (item.get("resource_type") or "").lower()
		label = labels.get(rtype)
		parts.append(f"{qty:g} {label}" if label else f"{qty:g} {item.get('unit') or rtype}".strip())
	return " · ".join(p for p in parts if p)


def _provider_region(cluster: str | None) -> tuple[str | None, str | None]:
	"""Split a cluster slug into (provider, 'City, Country') for the Change-plan header."""
	from central.billing.regions import REGION_META

	meta = REGION_META.get((cluster or "").lower())
	if not meta:
		return None, None
	city, country, provider = meta
	return provider, ", ".join(part for part in [city, country] if part)


# Adapter → the one-line hint the Add-payment "Pay through" list shows.
_GATEWAY_HINT = {"Stripe": "Secure redirect", "Razorpay": "Opens here", "Paypal": "PayPal balance or card"}


def _gateway_options(currency: str) -> list[dict]:
	"""Enabled gateways that serve `currency`, one per adapter (Stripe/Razorpay/…),
	the default first — the 'Pay through' choices the Add-payment card renders."""
	rows = frappe.get_all("Payment Gateway Currency", {"currency": currency}, ["parent", "is_default"],
						  order_by="is_default desc")
	seen, out = set(), []
	for row in rows:
		gw = frappe.db.get_value(
			"Payment Gateway", row.parent,
			["name", "adapter_key", "is_enabled", "credentials_validated_at"], as_dict=True,
		)
		# Only offer a gateway that can actually process a payment — enabled AND its
		# credentials validated. (In production `enabled` implies validated; this also
		# filters out seed fixtures that skipped validation with fake keys.)
		if gw and gw.is_enabled and gw.credentials_validated_at and gw.adapter_key not in seen:
			seen.add(gw.adapter_key)
			out.append({"name": gw.name, "adapter_key": gw.adapter_key,
						"label": gw.adapter_key, "subtitle": _GATEWAY_HINT.get(gw.adapter_key, "")})
	return out


def _resolve_add_gateway(currency: str, chosen: str | None):
	"""The gateway to add a method on: the caller's choice (validated enabled + serving
	the currency), else the currency default."""
	if chosen:
		gw = frappe.db.get_value(
			"Payment Gateway", chosen,
			["name", "adapter_key", "is_enabled", "credentials_validated_at"], as_dict=True,
		)
		serves = frappe.db.exists("Payment Gateway Currency", {"parent": chosen, "currency": currency})
		# Require validated credentials so an unconfigured/fake gateway fails cleanly
		# here (a clear message) instead of 500-ing deep in the gateway SDK.
		if not (gw and gw.is_enabled and gw.credentials_validated_at and serves):
			frappe.throw(frappe._("{0} is not a configured gateway for {1}.").format(chosen, currency), frappe.ValidationError)
		return gw
	return _add_method_gateway(currency)


def _payment_method_rows(team: str) -> list[dict]:
	"""The team's saved payment methods, display-ready (default first)."""
	rows = frappe.get_all(
		"Payment Method", {"team": team},
		["name", "method_type", "display_label", "is_default", "status"],
		order_by="is_default desc, priority asc, creation asc",
	)
	return [
		{"name": r.name, "label": r.display_label or r.method_type or r.name,
		 "method_type": r.method_type, "is_default": bool(r.is_default), "status": r.status}
		for r in rows
	]


# ── Payment methods ──────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_payment_gateways() -> list[dict]:
	"""The gateways the team can pay through (one per adapter, default first) — the
	'Pay through' options the Add-payment card renders."""
	team = _team()
	frappe.set_user("Administrator")
	return _gateway_options(_team_currency(team))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def add_payment_method(method_type: str = "Card", contact: str | None = None,
					   gateway: str | None = None) -> dict:
	"""Begin adding a payment method for the team. `gateway` is the caller's chosen
	'Pay through' option (from `get_payment_gateways`); when omitted, the gateway that
	serves the billing currency is used. Real card/UPI details are collected client-side
	by the gateway SDK/Checkout — this returns the handles that flow completes, plus the
	pending Payment Method to confirm via `confirm_payment_method`.

	`contact` is the phone Razorpay requires for a recurring card when the team's
	billing profile has none.
	"""
	from central.billing.payments import mandates, payments

	team = _team()
	# Server-side backstop: no money movement until the billing profile (esp. currency)
	# is complete — else _team_currency falls back to INR and routes to the wrong gateway.
	_require_billing_setup(team)
	currency = _team_currency(team)
	gw = _resolve_add_gateway(currency, gateway)
	gateway = gw.get("name")
	print(f"gateway: {gateway}")
	if not gateway:
		frappe.throw(frappe._("No payment gateway is configured for {0}.").format(currency), frappe.ValidationError)

	adapter_key = gw.get("adapter_key")
	if adapter_key == "Razorpay":
		if method_type == "UPI Autopay":
			handles = mandates.setup_mandate(team, gateway)
		else:
			handles = mandates.setup_card(team, gateway, contact=contact)
	else:
		handles = payments.initiate_payment_method_setup(team, gateway)

	return {**handles, "gateway": gateway, "adapter_key": adapter_key, "method_type": method_type}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def confirm_payment_method(
	payment_method: str,
	gateway_method_id: str | None = None,
	display_label: str | None = None,
	expiry_month: int | None = None,
	expiry_year: int | None = None,
	razorpay_payment_id: str | None = None,
	razorpay_order_id: str | None = None,
	razorpay_signature: str | None = None,
	razorpay_token_id: str | None = None,
) -> dict:
	"""Finalize the payment method the gateway SDK/Checkout tokenised. Routes by the
	method's gateway: Stripe runs the card micro-charge validation; Razorpay verifies
	the Checkout callback signature and activates the mandate/token."""
	from central.billing.payments import mandates, payments

	method_row = frappe.db.get_value("Payment Method", payment_method, ["team", "gateway"], as_dict=True)
	_assert_owns(method_row.team if method_row else None)
	adapter_key = frappe.db.get_value("Payment Gateway", method_row.gateway, "adapter_key")

	if adapter_key == "Razorpay":
		method = mandates.confirm_mandate(payment_method, {
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_order_id": razorpay_order_id,
			"razorpay_signature": razorpay_signature,
			"razorpay_token_id": razorpay_token_id,
		})
	else:
		method = payments.confirm_payment_method(
			payment_method, gateway_method_id=gateway_method_id, display_label=display_label,
			expiry_month=expiry_month, expiry_year=expiry_year,
		)

	return {"payment_method": method.name, "status": method.status}


# ── Add a card via hosted setup checkout (Stripe) ─────────────────────────────
# The hosted parallel of the top-up: Central opens a Stripe Checkout session in
# `setup` mode, the site redirects to it, the customer saves the card there, then
# `confirm_payment_method_checkout` reads the saved card back and validates it
# (micro-charge) → Active. No card data ever touches the site.


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_payment_method_checkout(redirect_url: str, gateway: str | None = None) -> dict:
	"""Start adding a card via hosted setup checkout. Returns `{checkout_url,
	reference, gateway}`; redirect the payer to `checkout_url`, then poll
	`confirm_payment_method_checkout`. Stripe only for now (hosted `setup` mode)."""
	from central.billing.payments import payments
	from central.billing.gateways.registry import get_adapter

	team = _team()
	_require_billing_setup(team)
	currency = _team_currency(team)
	gw = _resolve_add_gateway(currency, gateway)
	gw_doc = frappe.get_doc("Payment Gateway", gw.get("name"))
	if gw_doc.adapter_key != "Stripe":
		frappe.throw(frappe._("Hosted card setup is available on Stripe for now."), frappe.ValidationError)

	adapter = get_adapter(gw_doc)
	payments._discard_abandoned_setups(team, gw_doc.name)  # reap prior never-finished attempts
	customer = payments.ensure_gateway_customer(team, gw_doc.name, adapter)
	session = adapter.create_setup_checkout_session(customer, success_url=redirect_url, cancel_url=redirect_url)
	# Persist the checkout session on the pending row so the setup can be reconciled
	# on return (or by a webhook) even if the poll below never runs.
	method = frappe.get_doc({
		"doctype": "Payment Method", "team": team, "gateway": gw_doc.name,
		"method_type": "Card", "status": "Pending Validation", "gateway_customer_id": customer,
		"setup_reference": session["session_id"],
	}).insert(ignore_permissions=True)
	reference = f"{gw_doc.name}|{session['session_id']}|{method.name}"
	return {"checkout_url": session["checkout_url"], "reference": reference,
			"gateway": gw_doc.name, "adapter_key": gw_doc.adapter_key}


def _activate_setup(method_name: str, gateway: str, session_id: str) -> dict:
	"""Read a completed hosted setup back and validate the card (micro-charge) → Active.
	Returns `{status, active, label}`; `pending` while the gateway hasn't saved it yet."""
	from central.billing.payments import payments
	from central.billing.gateways.registry import get_adapter

	result = get_adapter(frappe.get_doc("Payment Gateway", gateway)).get_setup_result(session_id)
	if not result.get("payment_method"):
		return {"status": "pending", "active": False}
	label = f"{result.get('brand') or 'Card'} ···· {result['last4']}" if result.get("last4") else result.get("brand")
	method = payments.confirm_payment_method(
		method_name, gateway_method_id=result["payment_method"], display_label=label,
		expiry_month=result.get("exp_month"), expiry_year=result.get("exp_year"),
	)
	return {"status": method.status, "active": method.status == "Active", "label": method.display_label}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def confirm_payment_method_checkout(reference: str) -> dict:
	"""Poll a hosted card setup. Once the gateway reports the card saved, store its
	handle and validate it (micro-charge) → Active. Returns `{status, active, label}`."""
	gateway, session_id, method_name = reference.split("|", 2)
	method_row = frappe.db.get_value("Payment Method", method_name, ["team", "gateway"], as_dict=True)
	_assert_owns(method_row.team if method_row else None)

	frappe.set_user("Administrator")  # confirm gates on capability; team fixed by credential
	result = _activate_setup(method_name, gateway, session_id)
	if result["status"] == "pending":
		result["message"] = "Awaiting card entry."
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def remove_payment_method(payment_method: str) -> dict:
	"""Remove one of the team's payment methods (promotes another active one to
	default). Ownership is checked against the credential's team."""
	from central.billing.payments import payments

	method_row = frappe.db.get_value("Payment Method", payment_method, ["team"], as_dict=True)
	_assert_owns(method_row.team if method_row else None)
	frappe.set_user("Administrator")
	return payments.delete_payment_method(payment_method)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def reconcile_payment_setup() -> dict:
	"""Activate any card whose hosted setup finished while the caller was away — the
	no-webhook backstop the Billing tab calls on open, so a card added on the gateway's
	page shows up on return without the poll button. Returns `{activated}`."""
	team = _team()
	frappe.set_user("Administrator")
	pending = frappe.get_all(
		"Payment Method",
		filters={"team": team, "method_type": "Card", "status": "Pending Validation",
				 "gateway_method_id": ["in", [None, ""]]},
		fields=["name", "gateway", "setup_reference"],
	)
	activated = 0
	for row in pending:
		if not row.setup_reference:
			continue
		try:
			if _activate_setup(row.name, row.gateway, row.setup_reference).get("active"):
				activated += 1
		except Exception:
			frappe.clear_last_message()  # a decline/gateway hiccup must not break the tab load
	return {"activated": activated}


# ── Plans ────────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_available_plans(asset: str) -> dict:
	"""Active plans the team can switch `asset` to — priced for the team's currency on
	the asset's cluster, admitted by the trust tier, and within remaining headroom.
	Grouped by sub-category. The asset's cluster is resolved here; the underlying plan
	menu keys on cluster."""
	from central.billing.api.dashboard.catalog import get_eligible_plans

	team = _team()
	cluster = frappe.db.get_value("Asset", asset, "cluster")
	# The delegated menu gates on the session user's capability; the pilot is a Guest
	# session, so act as operator — the team is fixed from the verified credential.
	frappe.set_user("Administrator")
	return get_eligible_plans(cluster=cluster, team=team)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def change_plan(asset: str | None = None, plan: str | None = None) -> dict:
	"""Switch the asset's server onto a preset `plan`: validates + re-locks the rate at
	the current rate card and queues the VM reshape (stop→resize→start). Resolves the
	subscription from (team, asset). `asset` defaults to the credential's asset.
	Returns `{queued, resized}`."""
	from central.billing.api.dashboard.catalog import resize_server

	asset = asset or _asset()
	if not plan:
		frappe.throw(frappe._("A plan is required."), frappe.ValidationError)
	subscription = frappe.db.get_value("Subscription", {"team": _team(), "asset_id": asset}, "name")
	if not subscription:
		frappe.throw(frappe._("No subscription for asset {0} on this team.").format(asset), frappe.ValidationError)
	# resize_server gates on the session user's capability; act as operator (team is
	# fixed by the subscription lookup above, which is already scoped to the credential).
	frappe.set_user("Administrator")
	return resize_server(subscription, plan=plan)


# ── Credits ──────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_credit_balance() -> dict:
	"""The team's current prepaid wallet balance: `{"balance", "currency"}`."""
	from central.billing.revenue import credits

	return credits.get_balance(_team())


# ── Billing profile / address ────────────────────────────────────────────────

# The profile fields a caller may set (currency + legal identity + billing address);
# GSTIN is validated by the Billing Profile controller on save.
_PROFILE_FIELDS = (
	"currency", "legal_name", "email", "phone", "gstin",
	"address_line1", "address_line2", "city", "state", "country", "pincode",
)


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_billing_profile() -> dict:
	"""The team's billing profile (stored fields plus derived setup state:
	complete / missing / currency_locked / supported_currencies)."""
	from central.billing.api.dashboard.account import get_billing_profile as _get

	team = _team()
	# The delegated read gates on the session user's capability; act as operator (team
	# is fixed from the verified credential).
	frappe.set_user("Administrator")
	return _get(team)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def save_billing_profile(**fields) -> dict:
	"""Create/update the team's billing identity + address. Only the profile fields
	are accepted; the GSTIN is validated in the controller on save."""
	from central.billing.payments import profile

	team = _team()
	values = {k: v for k, v in fields.items() if k in _PROFILE_FIELDS}
	# Write gates on the session user's capability; the pilot is a Guest session, so
	# act as operator — the team is fixed from the verified credential.
	frappe.set_user("Administrator")
	doc = profile.create_or_update_billing_profile(team, **values)
	return {"saved": True, "team": team, "currency": doc.currency, "gstin": doc.gstin}


# ── In-app Billing tab (composed summary + plan options) ──────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_billing_summary() -> dict:
	"""Everything the in-app Billing tab renders for this bench's server: current plan
	(+ spec labels for the usage meters), the cycle estimate, the credit balance (with
	an insufficient-balance flag) and whether a payment method / profile exist. Usage
	percentages are filled in by the bench (host-local)."""
	from central.billing.api.dashboard._shared import _profile_complete
	from central.billing.api.dashboard.invoices import get_forecast
	from central.billing.revenue import credits

	team, asset = _team(), _asset()
	frappe.set_user("Administrator")  # act as operator; team + asset fixed by credential

	currency = _team_currency(team)
	fields = ["title", "plan", "vcpus", "memory_megabytes", "disk_gigabytes"]
	row = frappe.db.get_value("Asset", asset, fields, as_dict=True) or frappe._dict()
	specs = _resolve_specs(row, row.plan)
	subtitle = " · ".join(value for value in specs.values() if value)
	plan_title = frappe.db.get_value("Plan", row.plan, "title") if row.plan else None

	forecast = get_forecast(team)
	projected = frappe.utils.flt(forecast.get("projected_total"))
	balance = frappe.utils.flt(credits.get_balance(team, currency)["balance"])
	# Only an Active method counts as "set up" — a Pending Validation / Failed one
	# must not masquerade as the team's payment method on the summary.
	methods = [m for m in _payment_method_rows(team) if m["status"] == "Active"]
	default = next((m for m in methods if m["is_default"]), methods[0] if methods else None)

	return {
		"currency": currency,
		"plan": {"name": plan_title or row.plan, "subtitle": subtitle, "specs": specs},
		"estimate": {"amount": _money(projected, currency), "note": _estimate_note(forecast)},
		"credit": {
			"amount": _money(balance, currency),
			"note": frappe._("Insufficient balance") if balance < projected else frappe._("Available credit"),
			"warning": balance < projected,
		},
		"payment_method": {"label": default["label"], "name": default["name"]} if default else None,
		"profile_complete": _profile_complete(team),
	}


def _estimate_note(forecast: dict) -> str | None:
	end = forecast.get("period_end")
	if not end:
		return None
	days_left = frappe.utils.date_diff(end, frappe.utils.nowdate())
	return frappe._("Due {0} · {1}d left").format(frappe.utils.formatdate(end), max(0, days_left))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_plan_options() -> dict:
	"""Plans this bench's server can switch to, flattened + priced for the Change-plan
	list, plus the provider/region header and an insufficient-headroom flag."""
	from central.billing.api.dashboard.catalog import get_eligible_plans

	team, asset = _team(), _asset()
	row = frappe.db.get_value("Asset", asset, ["cluster", "plan"], as_dict=True) or frappe._dict()
	subscription = frappe.db.get_value("Subscription", {"team": team, "asset_id": asset}, "name")
	frappe.set_user("Administrator")

	menu = get_eligible_plans(cluster=row.cluster, team=team, exclude_subscription=subscription or None)
	currency = menu.get("currency") or _team_currency(team)
	provider, region = _provider_region(row.cluster)

	plans = [
		{"name": p["plan"], "title": p["title"], "subtitle": _includes_spec_line(p.get("includes")),
		 "price": frappe._("{0}/mo").format(_money(p.get("rate"), currency)),
		 "is_current": p["plan"] == row.plan}
		for rows in (menu.get("plans") or {}).values()
		for p in rows
	]
	# The running plan may be outside the eligible set (no headroom to re-pick) — always
	# show it, marked Current, so the list reflects what's actually running.
	if row.plan and not any(p["is_current"] for p in plans):
		plans.insert(0, {"name": row.plan, "title": frappe.db.get_value("Plan", row.plan, "title") or row.plan,
						 "subtitle": " · ".join(_asset_specs(
							 frappe.db.get_value("Asset", asset, ["vcpus", "memory_megabytes", "disk_gigabytes"],
												 as_dict=True) or frappe._dict()).values()),
						 "price": "", "is_current": True})

	return {"currency": currency, "provider": provider, "region": region,
			"current": row.plan, "plans": plans, "sufficient": frappe.utils.flt(menu.get("available")) > 0}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def list_payment_methods() -> list[dict]:
	"""The team's saved payment methods (label, type, default), default first."""
	team = _team()
	frappe.set_user("Administrator")
	return _payment_method_rows(team)


# ── Checkout (hosted URL + poll for status) ──────────────────────────────────
# A hosted-checkout flow for both gateways: create a Stripe Checkout Session / a
# Razorpay Payment Link for an amount, hand back the URL to redirect to, then poll
# get_checkout_status until the gateway reports paid. Stateless — the reference
# carries everything needed and the authoritative amount/currency are read back
# from the gateway, so no pending record is stored. A top-up credit is keyed on the
# underlying gateway payment id (the same id the capture webhook uses), so polling
# and the webhook backstop dedupe to a single credit.


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_topup_checkout(amount: float, redirect_url: str) -> dict:
	"""Start a wallet top-up via hosted checkout. Returns `{checkout_url, reference,
	gateway}`; redirect the payer to `checkout_url`, then poll `get_checkout_status`."""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	team = _team()
	# Same backstop as top-ups in the dashboard: require a complete profile (currency)
	# before money moves, so the wallet can't be locked to the INR fallback currency.
	_require_billing_setup(team)
	currency = _team_currency(team)
	return _create_hosted_checkout(
		team, currency, amount, purpose="topup", target=team, redirect_url=redirect_url,
		notes={"team": team, "purpose": "wallet_topup"},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_invoice_checkout(invoice: str, redirect_url: str) -> dict:
	"""Start an on-session payment of an open invoice via hosted checkout. Returns
	`{checkout_url, reference, gateway}`; the invoice settles to Paid on the gateway
	webhook (webhook-truth), which `get_checkout_status` reports."""
	inv = frappe.get_doc("Invoice", invoice)
	_assert_owns(inv.team)
	if inv.status not in ("Open", "Overdue"):
		frappe.throw("Invoice is not open for payment.", frappe.ValidationError)
	amount = frappe.utils.flt(inv.expected_collection)
	if amount <= 0:
		frappe.throw("Nothing is due on this invoice.", frappe.ValidationError)
	return _create_hosted_checkout(
		inv.team, inv.currency, amount, purpose="invoice", target=invoice, redirect_url=redirect_url,
		notes={"team": inv.team, "invoice": invoice, "purpose": "invoice_payment"},
	)


def _create_hosted_checkout(team, currency, amount, purpose, target, redirect_url, notes) -> dict:
	"""Create a hosted Stripe Checkout Session / Razorpay Payment Link on the gateway
	that serves the currency, and return the URL + a reference to poll."""
	from central.billing.api.dashboard._shared import _gateway_for_currency
	from central.billing.gateways.registry import get_adapter
	from central.billing.payments.payments import ensure_gateway_customer

	gateway = _gateway_for_currency(currency)
	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	# Stripe binds the session to the team's reused customer; Razorpay links take none.
	customer = ensure_gateway_customer(team, gateway, adapter) if gw_doc.adapter_key == "Stripe" else None
	receipt = f"{purpose}-{target}-{frappe.generate_hash(length=8)}"
	session = adapter.create_checkout_session(
		amount, currency, receipt, success_url=redirect_url, cancel_url=redirect_url,
		notes=notes, customer=customer,
	)
	reference = f"{gateway}|{session['session_id']}|{purpose}|{target}"
	return {"checkout_url": session["checkout_url"], "reference": reference,
			"gateway": gateway, "adapter_key": gw_doc.adapter_key, "amount": amount, "currency": currency}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def get_checkout_status(reference: str) -> dict:
	"""Poll a hosted checkout. Returns `{status, success, message, ...}`. On the first
	observed `paid`: a top-up credits the wallet idempotently and returns the new
	balance; an invoice reports success (it flips to Paid on the gateway webhook)."""
	from central.billing.gateways.registry import get_adapter

	gateway, session_id, purpose, target = reference.split("|", 3)
	# Ownership: a top-up's target is the team; an invoice's target is the invoice.
	if purpose == "topup":
		_assert_owns(target)
	else:
		_assert_owns(frappe.db.get_value("Invoice", target, "team"))

	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	session = adapter.get_checkout_session(session_id)
	paid, amount, currency, payment_id = _read_session(gw_doc.adapter_key, session)

	if not paid:
		return {"status": "pending", "success": False, "message": "Awaiting payment."}

	if purpose == "topup":
		from central.billing.revenue import credits

		# Key on the UNDERLYING payment id (Stripe pi_/Razorpay pay_), the same id the
		# capture webhook credits on — so poll and webhook dedupe to a single credit.
		# (Falls back to the session id only if the gateway hasn't surfaced one yet.)
		key = payment_id or session_id
		credits.purchase(target, amount, currency, gateway_payment_id=key,
						 reference_name=key, note=f"Wallet top-up ({key})")
		return {"status": "paid", "success": True, "message": "Wallet topped up.",
				"balance": credits.get_balance(target)["balance"]}

	return {"status": "paid", "success": True, "message": "Payment received; invoice settling.",
			"invoice": target, "invoice_status": frappe.db.get_value("Invoice", target, "status")}


def _read_session(adapter_key: str, session: dict) -> tuple:
	"""Normalise a gateway checkout object to `(paid, amount_major, currency, payment_id)`.

	`payment_id` is the UNDERLYING payment — Stripe's PaymentIntent (`pi_…`), Razorpay's
	captured payment (`pay_…`) — not the session/link id. It is the same id the capture
	webhook credits on, so keying the poll credit on it makes poll and webhook dedupe."""
	if adapter_key == "Razorpay":
		paid = session.get("status") == "paid"
		minor = session.get("amount_paid") or session.get("amount") or 0
		payments = session.get("payments") or []
		captured = next((p for p in payments if p.get("status") == "captured"), None)
		payment_id = (captured or (payments[0] if payments else {})).get("payment_id")
	else:  # Stripe Checkout Session
		paid = session.get("payment_status") == "paid"
		minor = session.get("amount_total") or 0
		payment_id = session.get("payment_intent")
	return paid, frappe.utils.flt(minor) / 100.0, (session.get("currency") or "").upper(), payment_id
