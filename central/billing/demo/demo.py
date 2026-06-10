# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Demo seed — a rich, self-consistent billing team for the Desk demo.

    bench --site central.local execute central.billing.demo.demo.seed

Idempotent: re-running wipes the demo team's data and rebuilds it. Produces a
paid invoice + an open invoice (fixed + metered + GST lines), a funded wallet
with a top-up and an applied-credit debit, an active card, a subscription, the
plan catalog, a GST tax profile, and a Billing workspace to navigate it all.
"""

import frappe

from central.billing.revenue import invoicing, credits
from central.billing.catalog import subscriptions
from central.billing.catalog.pricing import set_catalog_rates
from central.billing.platform.sync import receive_meter_rollups, receive_usage_events

TEAM = "demo"
CLUSTER = "ap-south-1"
PLAN = "bundle-2vcpu"
ADDON = "addon-transfer"
GATEWAY = "GW-Demo-Stripe"
RESOURCE = "srv-demo-web-1"


def seed():
	"""Build (or rebuild) the demo team end to end."""
	_wipe()
	_catalog()
	_gateway()
	_tier_and_tax()
	card = _payment_method()
	sub = subscriptions.create_subscription(
		team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="Monthly"
	).name

	# Runtime from 1 May: a full May (paid) and a partial-changed June (open).
	receive_usage_events([_event("ev-demo-1", RESOURCE, 3200, "2026-05-01 00:00:00", "subscribed")])
	# A mid-June plan bump to a pricier rate shows multi-segment day-weighting.
	receive_usage_events([_event("ev-demo-2", RESOURCE, 4800, "2026-06-12 00:00:00", "changed")])
	# Metered transfer: 150 GB used against a 100 GB allowance -> 50 GB overage.
	receive_meter_rollups([_meter(150)])

	# Wallet: a 5,000 top-up.
	credits.purchase(TEAM, 5000, "INR", note="Demo top-up")

	_paid_invoice(sub)
	_open_invoice(sub, card)
	_ensure_workspace()

	frappe.db.commit()
	return {
		"team": TEAM,
		"invoices": frappe.get_all("Invoice", {"team": TEAM}, pluck="name"),
		"wallet_balance": credits.get_balance(TEAM)["balance"],
	}


# --- building blocks --------------------------------------------------------


def _event(event_id, resource_id, rate, effective_from, event_type):
	return {
		"event_id": event_id,
		"team": TEAM,
		"resource_id": resource_id,
		"cluster": CLUSTER,
		"plan": PLAN,
		"shown_rate": rate,
		"currency": "INR",
		"event_type": event_type,
		"effective_from": effective_from,
		"effective_to": None,
	}


def _meter(qty):
	return {
		"resource_id": RESOURCE,
		"resource_type": "Transfer",
		"meter_type": "Counter",
		"period_start": "2026-06-01 00:00:00",
		"period_end": "2026-06-30 23:59:59",
		"quantity": qty,
		"unit": "GB",
		"idempotency_key": f"{RESOURCE}:counter:2026-06-01",
		"status": "closed",
	}


def _catalog():
	plan = _replace(
		"Plan",
		PLAN,
		{
			"title": "2 vCPU Bundle",
			"billing_cycle": "Monthly",
			"is_active": 1,
			"includes": [
				{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 4, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 80, "unit": "GB"},
				{"resource_type": "Transfer", "quantity": 100, "unit": "GB"},
			],
		},
	)
	set_catalog_rates(
		"Plan",
		plan,
		[
			{"cluster": "", "currency": "USD", "rate": 40},
			{"cluster": "", "currency": "INR", "rate": 3200},
		],
	)
	addon = _replace(
		"Add-on",
		ADDON,
		{
			"title": "Bandwidth Overage",
			"resource_type": "Transfer",
			"unit": "GB",
			"billing_type": "Metered",
			"billing_interval": "Monthly",
		},
	)
	set_catalog_rates("Add-on", addon, [{"cluster": "", "currency": "INR", "rate": 0.8}])


def _gateway():
	_replace(
		"Payment Gateway",
		GATEWAY,
		{
			"title": "Stripe (Demo)",
			"adapter_key": "Stripe",
			"currencies": [{"currency": "INR", "is_default": 1}],
			"api_secret": "sk_test_demo",
			"webhook_secret": "whsec_demo",
			"is_enabled": 1,
		},
	)


def _tier_and_tax():
	for tier, default, cap in (("t0", 1, 10000), ("t1", 0, 50000)):
		if not frappe.db.exists("Trust Tier Level", tier):
			frappe.get_doc(
				{
					"doctype": "Trust Tier Level",
					"__newname": tier,
					"tier": tier,
					"sequence": 0 if default else 1,
					"is_default": default,
					"max_spend": cap,
					"max_resource_count": 5 if default else 50,
					"min_paid_invoices": 0 if default else 1,
					"min_cumulative_paid": 0 if default else 3000,
				}
			).insert(ignore_permissions=True)
	# A paid (t1) team, so invoices are billable rather than cost_report.
	_replace(
		"Trust Tier",
		TEAM,
		{"tier": "t1", "level": "t1", "max_spend": 50000, "max_resource_count": 50, "manual_override": 1},
	)
	_replace(
		"Tax Profile",
		TEAM,
		{"output_tax_type": "GST", "output_tax_rate": 18},
	)


def _payment_method():
	name = frappe.db.get_value("Payment Method", {"team": TEAM, "gateway": GATEWAY}, "name")
	values = {
		"doctype": "Payment Method",
		"team": TEAM,
		"gateway": GATEWAY,
		"method_type": "Card",
		"status": "Active",
		"display_label": "Visa ····4242",
		"gateway_method_id": "pm_demo",
		"gateway_customer_id": "cus_demo",
		"expiry_month": 11,
		"expiry_year": 2030,
		"is_default": 1,
		"validated_at": frappe.utils.now_datetime(),
	}
	if name:
		frappe.delete_doc("Payment Method", name, force=True)
	return frappe.get_doc(values).insert(ignore_permissions=True).name


def _paid_invoice(sub):
	name = invoicing.generate_draft_invoice(sub, "2026-05-01", "2026-05-31")
	if not name:
		return
	# Settle May fully (demo: mark paid directly, no live gateway round-trip).
	inv = frappe.get_doc("Invoice", name)
	inv.status = "Paid"
	inv.amount_paid = inv.expected_collection
	inv.due_date = "2026-06-07"
	inv.save(ignore_permissions=True)


def _open_invoice(sub, card):
	name = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")
	if not name:
		return
	# Leave June outstanding (no credits drawn) so the demo shows a funded wallet
	# AND an open invoice — the postpaid "outstanding" wireframe. The credits-then
	# -card waterfall itself is covered by the test suite.
	inv = frappe.get_doc("Invoice", name)
	inv.status = "Open"
	inv.due_date = "2026-07-07"
	inv.save(ignore_permissions=True)


# --- helpers ----------------------------------------------------------------


def _replace(doctype, name, values):
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=True)
	field = "__newname" if doctype in ("Plan", "Add-on", "Payment Gateway") else None
	doc = {"doctype": doctype, **values}
	if doctype in ("Trust Tier", "Tax Profile"):
		doc["team"] = name
	elif field:
		doc[field] = name
	else:
		doc["__newname"] = name
	return frappe.get_doc(doc).insert(ignore_permissions=True).name


def _wipe():
	for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
		frappe.db.delete("Subscription Change", {"subscription": sub})
	for dt in (
		"Invoice", "Payment Attempt", "Payment Method", "Price Lock", "Usage Rollup",
		"Credit Ledger Entry", "Subscription",
	):
		frappe.db.delete(dt, {"team": TEAM})
	for dt in ("Credit Wallet", "Trust Tier", "Tax Profile"):
		if frappe.db.exists(dt, TEAM):
			frappe.delete_doc(dt, TEAM, force=True)
	frappe.db.commit()


def _ensure_workspace():
	if frappe.db.exists("Workspace", "Billing"):
		frappe.delete_doc("Workspace", "Billing", force=True)

	shortcuts = [
		("Invoices", "Invoice", "Blue"),
		("Payment Methods", "Payment Method", "Green"),
		("Credit Ledger", "Credit Ledger Entry", "Orange"),
		("Subscriptions", "Subscription", "Purple"),
	]
	cards = {
		"Billing Records": ["Invoice", "Payment Attempt", "Credit Ledger Entry", "Price Lock", "Usage Rollup"],
		"Catalog & Config": ["Plan", "Add-on", "Payment Gateway", "Tax Profile", "Trust Tier"],
	}
	links = []
	for card_name, doctypes in cards.items():
		links.append({"type": "Card Break", "label": card_name})
		for dt in doctypes:
			links.append({"type": "Link", "label": dt, "link_type": "DocType", "link_to": dt})

	content = [{"type": "header", "data": {"text": "Cloud Billing", "col": 12}}]
	for label, _dt, _color in shortcuts:
		content.append({"type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
	for card_name in cards:
		content.append({"type": "Card", "data": {"card_name": card_name, "col": 4}})

	frappe.get_doc(
		{
			"doctype": "Workspace",
			"name": "Billing",
			"title": "Billing",
			"label": "Billing",
			"module": "Billing",
			"public": 1,
			"icon": "money-coin-1",
			"content": frappe.as_json(content),
			"shortcuts": [
				{"type": "DocType", "label": label, "link_to": dt, "color": color}
				for (label, dt, color) in shortcuts
			],
			"links": links,
		}
	).insert(ignore_permissions=True)
