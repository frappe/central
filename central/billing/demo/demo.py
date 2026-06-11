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
	_team_and_members()
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

	# Settle both months through the real credits-then-card waterfall (#11):
	#  - May (~3,776) is fully covered by the wallet → Paid from credits, no card.
	#  - June (~5,018) exhausts the remaining credits, the card covers the rest.
	may = invoicing.generate_draft_invoice(sub, "2026-05-01", "2026-05-31")
	_settle(may, card, due_date="2026-06-07")
	june = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")
	# June's card is declined once, then captured on retry — a richer timeline.
	_settle(june, card, due_date="2026-07-07", with_failure=True)
	_notifications()
	_ensure_workspace()

	frappe.db.commit()
	return {
		"team": TEAM,
		"invoices": frappe.get_all("Invoice", {"team": TEAM}, pluck="name"),
		"wallet_balance": credits.get_balance(TEAM)["balance"],
	}


# --- building blocks --------------------------------------------------------

# The roster the merged Members & Roles screen renders: an Owner plus members on
# the stock system roles, including a suspended one so status variety shows.
OWNER = "demo-owner@example.com"
OWNER_PASSWORD = "Central-Demo-2026!"
MEMBERS = [
	("finance@demo.example.com", "Priya Finance", "Billing", "Active"),
	("dev@demo.example.com", "Dev Kumar", "Developer", "Active"),
	("viewer@demo.example.com", "Sam Viewer", "Viewer", "Active"),
	("contractor@demo.example.com", "Contractor Singh", "Developer", "Suspended"),
]


def _demo_user_emails():
	return [OWNER] + [m[0] for m in MEMBERS]


def _ensure_user(email, full_name):
	"""Create the user DISABLED so the after_insert hook doesn't bootstrap a
	personal team (central.users.bootstrap_user_team skips disabled users). They
	join the `demo` team explicitly, then get enabled — a save, not an insert, so
	the bootstrap never fires."""
	if frappe.db.exists("User", email):
		return email
	first, _, last = full_name.partition(" ")
	doc = frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": first,
		"last_name": last or None,
		"send_welcome_email": 0,
		"enabled": 0,
	})
	doc.insert(ignore_permissions=True)
	return email


def _team_and_members():
	"""Create Team `demo` with an Owner + members on system roles. Created before
	any billing data so the team Link resolves (team is Link(Team), #43)."""
	names = {OWNER: "Demo Owner", **{e: n for e, n, _r, _s in MEMBERS}}
	for email, full_name in names.items():
		_ensure_user(email, full_name)

	team = frappe.get_doc({
		"doctype": "Team",
		"team_name": TEAM,
		"owner_user": OWNER,
		"status": "Active",
	})
	# Force the readable name (bypass the TEAM-##### series) so `team` Links resolve
	# to "demo" — same trick the test util uses (tests.utils.ensure_team).
	team.flags.name_set = True
	team.name = TEAM
	# before_validate auto-appends the owner as the Owner member.
	for email, _name, role, status in MEMBERS:
		team.append("members", {"user": email, "role": role, "status": status})
	team.insert(ignore_permissions=True)

	# Now enable the accounts (save → no bootstrap). The owner can log in to view
	# the customer dashboard; members are roster-only.
	for email in _demo_user_emails():
		u = frappe.get_doc("User", email)
		u.enabled = 1
		u.user_type = "System User" if email == OWNER else "Website User"
		if email == OWNER:
			u.new_password = OWNER_PASSWORD
			u.flags.ignore_password_policy = True
		u.save(ignore_permissions=True)
	return team.name


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
	# The demo settles invoices directly (no live charge), so skip the credential
	# check + webhook auto-registration that would otherwise call Stripe.
	if frappe.db.exists("Payment Gateway", GATEWAY):
		frappe.delete_doc("Payment Gateway", GATEWAY, force=True)
	doc = frappe.get_doc({
		"doctype": "Payment Gateway",
		"__newname": GATEWAY,
		"title": "Stripe (Demo)",
		"adapter_key": "Stripe",
		"currencies": [{"currency": "INR", "is_default": 1}],
		"api_secret": "sk_test_demo",
		"webhook_secret": "whsec_demo",
		"is_enabled": 1,
	})
	doc.flags.skip_credential_validation = True
	doc.insert(ignore_permissions=True)


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


def _attempt(name, card, amount, status, when, retry, **extra):
	frappe.get_doc({
		"doctype": "Payment Attempt",
		"invoice": name,
		"team": TEAM,
		"gateway": GATEWAY,
		"payment_method": card,
		"amount": amount,
		"currency": "INR",
		"status": status,
		"initiated_at": when,
		"completed_at": when,
		"retry_number": retry,
		**extra,
	}).insert(ignore_permissions=True)


def _settle(name, card, due_date, with_failure=False):
	"""Settle an invoice through the real credits-then-card waterfall (#11),
	mirroring invoicing.open_and_collect without a live gateway round-trip:

	  1. Apply wallet credits first, up to the collectable amount.
	  2. If credits cover it in full → Paid, no card charge.
	  3. Otherwise capture the remainder on the card. `with_failure` adds a first
	     declined attempt, then captures on retry — a richer payment timeline.

	Card attempts are stamped a few minutes after the invoice/credit records so
	the per-invoice activity timeline stays in order (the wallet ledger is never
	backdated — that would break its running-balance anchor).
	"""
	if not name:
		return
	inv = frappe.get_doc("Invoice", name)

	collectable = frappe.utils.flt(inv.total) - frappe.utils.flt(inv.get("tds_amount") or 0)
	balance = credits.get_balance(TEAM)["balance"]
	applied = min(frappe.utils.flt(balance), collectable) if collectable > 0 else 0.0
	if applied > 0:
		credits.apply_credit(
			TEAM, applied, "INR",
			reference_type="Invoice", reference_name=name, note=f"Credit applied to {name}",
		)
	inv.credit_applied = applied
	inv.expected_collection = frappe.utils.flt(collectable - applied, 2)
	inv.due_date = due_date

	# Credits cover it in full — settled with no card charge.
	if inv.expected_collection <= 0:
		inv.amount_paid = 0
		inv.status = "Paid"
		inv.save(ignore_permissions=True)
		return

	# Charge the remainder on the card (simulated capture — no live gateway).
	now = frappe.utils.now_datetime()
	retry = 0
	if with_failure:
		_attempt(
			name, card, inv.expected_collection, "Failed",
			frappe.utils.add_to_date(now, minutes=10), 0,
			failure_code="card_declined", failure_reason="Your card was declined by the bank.",
		)
		retry = 1
	_attempt(
		name, card, inv.expected_collection, "Captured",
		frappe.utils.add_to_date(now, minutes=20), retry,
		gateway_transaction_id=f"pi_{frappe.generate_hash(length=24)}", resolved_by="Webhook",
	)

	inv.amount_paid = inv.expected_collection
	inv.status = "Paid"
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
		"Credit Ledger Entry", "Subscription", "Billing Notification Log",
	):
		frappe.db.delete(dt, {"team": TEAM})
	for dt in ("Credit Wallet", "Trust Tier", "Tax Profile", "Notification Preference"):
		if frappe.db.exists(dt, TEAM):
			frappe.delete_doc(dt, TEAM, force=True)
	for inv in frappe.get_all("Team Invitation", {"team": TEAM}, pluck="name"):
		frappe.delete_doc("Team Invitation", inv, force=True)
	if frappe.db.exists("Team", TEAM):
		frappe.delete_doc("Team", TEAM, force=True)
	# Drop any personal teams a prior run's bootstrap created for the demo users,
	# so the owner's default team resolves cleanly to `demo`.
	for email in _demo_user_emails():
		for t in frappe.get_all("Team", {"owner_user": email}, pluck="name"):
			frappe.delete_doc("Team", t, force=True)
	frappe.db.commit()


def _notifications():
	"""A few sent/suppressed entries so the Notifications feed isn't empty."""
	rows = [
		("Payment Success", "Sent", "Payment received", "We received ₹4,956.00 for invoice May."),
		("Invoice Overdue", "Sent", "Invoice overdue", "Invoice June is past its due date."),
		("Credit Low", "Suppressed", "Low wallet balance", "Your wallet is running low."),
		("Card Expiry", "Sent", "Card expiring soon", "Visa ····4242 expires 11/2030."),
	]
	for i, (event, status, subject, message) in enumerate(rows):
		frappe.get_doc({
			"doctype": "Billing Notification Log",
			"team": TEAM,
			"event_type": event,
			"channel": "Email",
			"status": status,
			"subject": subject,
			"message": message,
			"sent_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-i),
		}).insert(ignore_permissions=True)


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
