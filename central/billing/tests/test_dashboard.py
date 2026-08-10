# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Customer dashboard endpoints + forecast (issues #26, #18)."""

import frappe

from central.billing.api import dashboard
from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_billing_subscription,
	make_billing_team,
	make_custom_role_team,
	make_plan,
	make_user,
	reset_gateway_roster,
)

TEAM = "team-cust"
CLUSTER = "ap-south-1"
PLAN = "bundle-cust-test"


class TestDashboardSmoke(IntegrationTestCase):
	def test_whoami_returns_session_and_scope(self):
		out = dashboard.whoami()
		self.assertEqual(out["user"], frappe.session.user)
		self.assertIn("team", out)
		self.assertIn("is_operator", out)

	def test_whoami_operator_flag_for_administrator(self):
		self.assertTrue(dashboard.whoami()["is_operator"])


class CustomerDataBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		# Saving a billing profile derives the currency from the country and rejects
		# one no enabled gateway settles, so these tests need INR and USD routable —
		# set that up rather than inheriting whatever an earlier module left behind.
		reset_gateway_roster()
		self._purge()
		self.today = frappe.utils.getdate()
		self.month_start = frappe.utils.get_first_day(self.today)

	def tearDown(self):
		self._purge()

	def _purge(self):
		# Billing Profile + Tax Profile are purged too: completing a profile via the
		# API now provisions a tax profile and welcome credits, so a profile left
		# committed by one test would make a later test's partial save look complete
		# and fire that provisioning under it.
		for dt in ("Invoice", "Credit Ledger Entry", "Gateway Customer", "Tax Profile", "Billing Profile"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _provision(self, rate=3000):
		# The Subscription + its month-start segment IS the price-lock (ADR 0010): it
		# feeds _team_clusters, the resource count, and compute_line_items alike.
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", rate, f"{self.month_start} 00:00:00")
		return sub


class TestForecast(CustomerDataBase):
	def test_forecast_projects_month_end_vs_credit(self):
		self._provision(rate=3000)  # active all month → full-month projection
		credits.purchase(TEAM, 1000, "INR")

		fc = dashboard.get_forecast(TEAM)
		self.assertEqual(fc["projected_total"], 3000.0)
		self.assertEqual(fc["credit_balance"], 1000.0)
		self.assertEqual(fc["shortfall"], 2000.0)
		self.assertGreaterEqual(fc["days_remaining"], 0)
		self.assertTrue(fc["line_items"])

	def test_forecast_no_runtime_is_zero(self):
		fc = dashboard.get_forecast(TEAM)
		self.assertEqual(fc["projected_total"], 0)
		self.assertEqual(fc["shortfall"], 0)


class TestCustomerReads(CustomerDataBase):
	def _invoice(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Paid",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": 1000,
					"output_tax_type": "GST",
					"output_tax_amount": 180,
					"total": 1180,
					"amount_paid": 1180,
					"items": [
						{"resource_type": "bundle", "plan": PLAN, "rate": 1000, "days": 30, "amount": 1000}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_list_invoices_is_summary_only(self):
		self._invoice()
		rows = dashboard.list_invoices(TEAM)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["status"], "Paid")
		self.assertEqual(rows[0]["total"], 1180)

	def test_get_invoice_returns_items_and_tax(self):
		inv = self._invoice()
		detail = dashboard.get_invoice(inv)
		self.assertEqual(detail["output_tax_type"], "GST")
		self.assertEqual(detail["output_tax_amount"], 180)
		self.assertEqual(len(detail["items"]), 1)

	def test_get_invoice_flags_payment_in_progress(self):
		# An Open invoice with a captured-but-unsettled attempt is mid-settlement:
		# the flag lets the UI show a "settling" status instead of a Pay button.
		inv = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": 1000,
					"total": 1000,
					"expected_collection": 1000,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.assertFalse(dashboard.get_invoice(inv)["payment_in_progress"])

		attempt = frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv,
				"team": TEAM,
				"amount": 1000,
				"currency": "INR",
				"status": "Captured",
				"gateway_transaction_id": "pi_x",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(dashboard.get_invoice(inv)["payment_in_progress"])

		# Once it settles/fails (terminal), the flag clears and Pay is offered again.
		attempt.db_set("status", "Failed")
		self.assertFalse(dashboard.get_invoice(inv)["payment_in_progress"])

	def test_payment_methods_never_expose_secrets(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway().name
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": gw,
				"method_type": "Card",
				"status": "Active",
				"display_label": "Visa ····4242",
				"gateway_method_id": "pm_secret",
				"is_default": 1,
			}
		).insert(ignore_permissions=True)
		rows = dashboard.list_payment_methods(TEAM)
		self.assertEqual(rows[0]["display_label"], "Visa ····4242")
		# Gateway handle / secrets are not in the customer payload.
		self.assertNotIn("gateway_method_id", rows[0])
		self.assertNotIn("api_key", rows[0])
		frappe.db.delete("Payment Method", {"team": TEAM})

	def test_credit_ledger_and_balance(self):
		credits.purchase(TEAM, 500, "INR")
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 500)
		ledger = dashboard.credit_ledger(TEAM)
		self.assertEqual(ledger[0]["entry_type"], "Credit")

	def test_balance_reports_promotional_credit_on_a_clock(self):
		"""Purchased credit is not listed as expiring; a grant with a date is."""
		credits.purchase(TEAM, 500, "INR")
		credits.grant_promotional_credits(
			TEAM, 100, "INR", expires_on=frappe.utils.add_days(frappe.utils.nowdate(), 20)
		)

		balance = dashboard.get_credit_balance(TEAM)

		self.assertEqual(balance["balance"], 600)
		self.assertEqual(len(balance["expiring"]), 1)
		self.assertEqual(balance["expiring"][0]["amount"], 100)

	def test_get_trust_tier_reports_first_paid_and_last_invoice_amount(self):
		first = self._invoice()  # amount_paid 1180
		first_paid_at = frappe.utils.add_days(frappe.utils.now_datetime(), -10)
		frappe.db.set_value("Invoice", first, "paid_at", first_paid_at)

		second = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Paid",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "INR",
					"subtotal": 2000,
					"total": 2000,
					"amount_paid": 2000,
					"items": [
						{"resource_type": "bundle", "plan": PLAN, "rate": 2000, "days": 30, "amount": 2000}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("Invoice", second, "paid_at", frappe.utils.now_datetime())

		progress = dashboard.get_trust_tier(TEAM)["progress"]
		self.assertEqual(
			frappe.utils.get_datetime(progress["first_paid_at"]),
			frappe.utils.get_datetime(first_paid_at),
		)
		self.assertEqual(progress["last_paid_invoice_amount"], 2000)
		self.assertEqual(progress["cumulative_paid"], 3180)

	def test_get_trust_tier_progress_is_blank_with_no_paid_invoices(self):
		progress = dashboard.get_trust_tier(TEAM)["progress"]
		self.assertIsNone(progress["first_paid_at"])
		self.assertEqual(progress["last_paid_invoice_amount"], 0)

	def test_get_trust_tier_ignores_legacy_invoices_without_paid_at(self):
		# An invoice paid before paid_at existed has no reliable settlement time — it
		# must not be guessed at (via creation) for tenure, though its amount still
		# counts toward cumulative paid.
		self._invoice()  # amount_paid 1180, no paid_at set

		progress = dashboard.get_trust_tier(TEAM)["progress"]
		self.assertIsNone(progress["first_paid_at"])
		self.assertEqual(progress["last_paid_invoice_amount"], 0)
		self.assertEqual(progress["cumulative_paid"], 1180)


class TestTeamScoping(CustomerDataBase):
	def setUp(self):
		super().setUp()
		# These tests mint unique-hash teams inline (make_billing_team); snapshot the
		# roster so tearDown can purge exactly what each test added.
		self._teams_before = set(frappe.get_all("Team", pluck="name"))

	def tearDown(self):
		from central.billing.tests.utils import purge_teams

		purge_teams(list(set(frappe.get_all("Team", pluck="name")) - self._teams_before))
		super().tearDown()

	def test_customer_scoped_to_their_capable_team(self):
		"""A billing-capable member reads their own team (resolved as the default)
		but is rejected for any team they're not a member of — never widened."""
		user = make_user()
		team = make_billing_team(user)  # Billing role → billing:view + billing:manage
		frappe.set_user(user)
		try:
			dashboard.list_invoices()  # no arg → their own team, ok
			dashboard.list_invoices(team.name)  # own team by name, ok
			with self.assertRaises(frappe.PermissionError):
				dashboard.list_invoices("some-other-team")  # not a member → rejected
		finally:
			frappe.set_user("Administrator")

	def test_member_without_billing_capability_is_denied(self):
		"""A team member whose role carries no billing capability — Viewer or
		Developer, standing in for the role-less Agent key — gets a 403, whether
		reading or mutating."""
		for role in ("Viewer", "Developer"):
			with self.subTest(role=role):
				user = make_user()
				team = make_billing_team(user, role=role)
				frappe.set_user(user)
				try:
					with self.assertRaises(frappe.PermissionError):
						dashboard.list_invoices(team.name)
					with self.assertRaises(frappe.PermissionError):
						dashboard.save_billing_settings(team=team.name, min_balance=5000)
				finally:
					frappe.set_user("Administrator")

	def test_billing_capable_roles_can_read_and_manage(self):
		"""The system roles that carry both capabilities can read and run a manage
		mutation on their own team. Owner is the team's sole owner_user; Admin and
		Billing are separate members."""
		user = make_user()
		owner_team = frappe.get_doc(
			{"doctype": "Team", "team_name": f"Owned {frappe.generate_hash(5)}", "owner_user": user}
		).insert(ignore_permissions=True)  # user becomes the sole active Owner member
		admin_user = make_user()
		admin_team = make_billing_team(admin_user, role="Admin")
		billing_user = make_user()
		billing_team = make_billing_team(billing_user, role="Billing")

		cases = {
			"Owner": (user, owner_team.name),
			"Admin": (admin_user, admin_team.name),
			"Billing": (billing_user, billing_team.name),
		}
		for role, (member, team_name) in cases.items():
			with self.subTest(role=role):
				frappe.set_user(member)
				try:
					dashboard.list_invoices(team_name)  # read ok
					dashboard.save_billing_settings(team=team_name, min_balance=5000)  # manage ok
				finally:
					frappe.set_user("Administrator")
					frappe.db.delete("Billing Profile", {"team": team_name})

	def test_view_only_member_reads_but_cannot_manage(self):
		"""A member whose (custom) role grants `billing:view` WITHOUT
		`billing:manage` — a split no system role offers — may read every customer
		endpoint but is denied manage mutations."""
		user = make_user()
		team = make_custom_role_team(user, ["billing:view"])
		frappe.set_user(user)
		try:
			dashboard.list_invoices(team.name)  # read ok
			dashboard.get_credit_balance(team.name)  # read ok
			with self.assertRaises(frappe.PermissionError):
				dashboard.save_billing_settings(team=team.name, min_balance=5000)
			with self.assertRaises(frappe.PermissionError):
				dashboard.create_topup_order(team=team.name, amount=100)
		finally:
			frappe.set_user("Administrator")


class TestCustomerActions(CustomerDataBase):
	def tearDown(self):
		if frappe.db.exists("Billing Profile", TEAM):
			frappe.db.delete("Billing Profile", {"team": TEAM})
		super().tearDown()

	def test_gstin_validation(self):
		# 27 = Maharashtra: the GSTIN's state code must match the chosen state.
		dashboard.save_billing_profile(
			TEAM,
			legal_name="Acme Pvt Ltd",
			country="India",
			state="Maharashtra",
			gstin="27AAPFU0939F1ZV",
		)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "gstin"), "27AAPFU0939F1ZV")
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(TEAM, legal_name="Acme", state="Maharashtra", gstin="NOT-A-GSTIN")
		# state code mismatch (Karnataka is 29) is rejected too.
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(
				TEAM, legal_name="Acme", country="India", state="Karnataka", gstin="27AAPFU0939F1ZV"
			)

	def test_money_movement_blocked_until_profile_complete(self):
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		# No profile yet → a top-up is refused before any gateway call.
		with self.assertRaises(frappe.ValidationError):
			dashboard.create_topup_order(team=TEAM, amount=1500)
		setup = dashboard.get_billing_profile(TEAM)
		self.assertFalse(setup["complete"])
		self.assertIn("currency", setup["missing"])
		# Once the profile is complete, the same call reaches the gateway.
		complete_billing_profile(TEAM)
		self.assertTrue(dashboard.get_billing_profile(TEAM)["complete"])
		gw = make_razorpay_gateway().name
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_gate"
		adapter.create_order.return_value = {
			"order_id": "order_gate",
			"key_id": "rzp_test",
			"amount_in_subunits": 150000,
		}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = dashboard.create_topup_order(team=TEAM, amount=1500, gateway=gw)
		self.assertEqual(out["order_id"], "order_gate")

	def test_billing_settings_roundtrip(self):
		dashboard.save_billing_settings(team=TEAM, min_balance=5000)
		s = dashboard.get_billing_settings(TEAM)
		self.assertEqual(s["min_balance"], 5000)

	def test_admin_without_team_falls_back(self):
		from central.billing.catalog import subscriptions

		subscriptions.create_subscription(team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="Monthly")
		invoices = dashboard.list_invoices()  # no team arg, as admin
		self.assertIsInstance(invoices, list)


class TestBillingCurrency(CustomerDataBase):
	def tearDown(self):
		if frappe.db.exists("Billing Profile", TEAM):
			frappe.db.delete("Billing Profile", {"team": TEAM})
		super().tearDown()

	def test_currency_must_be_gateway_supported(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		make_razorpay_gateway()  # makes INR a supported currency
		dashboard.save_billing_profile(TEAM, currency="INR", legal_name="Acme")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(TEAM, currency="XYZ")  # no gateway → rejected

	def test_currency_follows_country(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		make_razorpay_gateway()  # INR supported
		make_stripe_gateway()  # USD supported

		# India → INR, regardless of any currency the client tries to send.
		dashboard.save_billing_profile(TEAM, legal_name="Acme", country="India", currency="USD")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")

		# A foreign country → USD.
		dashboard.save_billing_profile(TEAM, country="Germany")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "USD")

	def test_currency_locks_after_money_activity(self):
		from central.billing.revenue import credits
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		make_razorpay_gateway()
		dashboard.save_billing_profile(TEAM, currency="INR", legal_name="Acme")
		self.assertFalse(dashboard.get_billing_profile(TEAM)["currency_locked"])

		credits.purchase(TEAM, 100, "INR")  # first money activity locks currency
		self.assertTrue(dashboard.get_billing_profile(TEAM)["currency_locked"])
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(TEAM, currency="USD")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")
		# A locked INR team editing its (foreign) address does NOT get re-derived to USD.
		dashboard.save_billing_profile(TEAM, country="Germany", legal_name="Acme")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")


class TestGatewayTopUp(CustomerDataBase):
	def test_topup_goes_through_gateway_and_verifies(self):
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_topup"
		adapter.create_order.return_value = {
			"order_id": "order_x",
			"key_id": "rzp_test",
			"amount_in_subunits": 500000,
		}
		adapter.verify_payment_signature.return_value = True
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, gateway=gw)
			self.assertEqual(order["order_id"], "order_x")  # a real gateway order was created
			self.assertEqual(order["key_id"], "rzp_test")  # checkout `key` reaches the client
			# Human-currency amount survives the handles spread (paise lives under
			# amount_in_subunits) — this is what the client echoes to confirm_topup.
			self.assertEqual(order["amount"], 5000)
			adapter.create_order.assert_called_once()
			# The top-up minted + stored the team's gateway customer and passed it to
			# the order, so future transactions reuse the same id.
			self.assertEqual(adapter.create_order.call_args.kwargs["customer"], "cus_topup")
			self.assertEqual(
				frappe.db.get_value("Gateway Customer", {"team": TEAM, "gateway": gw}, "gateway_customer_id"),
				"cus_topup",
			)
			# Wallet is NOT credited yet — only after the gateway confirms.
			self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)

			adapter.get_payment.return_value = {"status": "captured", "amount": 500000, "currency": "INR"}
			out = dashboard.confirm_topup(
				team=TEAM,
				amount=5000,
				gateway=gw,
				razorpay_order_id="order_x",
				razorpay_payment_id="pay_x",
				razorpay_signature="sig",
			)
			adapter.verify_payment_signature.assert_called_once()
			# The credit is the gateway's captured figure, read server-side.
			adapter.get_payment.assert_called_once_with("pay_x")
			self.assertEqual(out["new_balance"], 5000)

	def test_topup_credits_gateway_amount_not_request_amount(self):
		"""The Razorpay callback signature binds order|payment, NOT the amount — a
		client claiming a bigger figure must be credited what the gateway captured."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.verify_payment_signature.return_value = True
		adapter.get_payment.return_value = {
			"status": "captured",
			"amount": 100,
			"currency": "INR",
		}  # ₹1 really captured
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = dashboard.confirm_topup(
				team=TEAM,
				amount=1000000,
				gateway=gw,
				razorpay_order_id="order_a",
				razorpay_payment_id="pay_a",
				razorpay_signature="sig",
			)
		self.assertEqual(out["new_balance"], 1)  # the gateway figure, not the claim
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 1)

	def test_topup_rejects_captured_payment_without_amount(self):
		"""A captured payment whose fetch carries no amount must hard-fail, not
		fall back to the client-supplied figure the signature never covered."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.verify_payment_signature.return_value = True
		adapter.get_payment.return_value = {"status": "captured", "currency": "INR"}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(
					team=TEAM,
					amount=1000000,
					gateway=gw,
					razorpay_order_id="order_n",
					razorpay_payment_id="pay_n",
					razorpay_signature="sig",
				)
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)

	def test_topup_rejects_uncaptured_payment(self):
		"""A signature-valid callback whose payment the gateway has not captured
		credits nothing."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.verify_payment_signature.return_value = True
		adapter.get_payment.return_value = {"status": "authorized", "amount": 500000}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(
					team=TEAM,
					amount=5000,
					gateway=gw,
					razorpay_order_id="order_b",
					razorpay_payment_id="pay_b",
					razorpay_signature="sig",
				)
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)

	def test_second_topup_reuses_the_same_gateway_customer(self):
		"""A team's customer is minted once and reused — the second top-up (or any
		later charge / payment-method setup) never mints a fresh one."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_once"
		adapter.create_order.return_value = {
			"order_id": "o",
			"key_id": "rzp_test",
			"amount_in_subunits": 100000,
		}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			dashboard.create_topup_order(team=TEAM, amount=1000, gateway=gw)
			adapter.create_customer.reset_mock()
			dashboard.create_topup_order(team=TEAM, amount=1000, gateway=gw)
			adapter.create_customer.assert_not_called()  # reused, not re-minted
			self.assertEqual(adapter.create_order.call_args.kwargs["customer"], "cus_once")

	def test_topup_rejects_bad_signature(self):
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway().name
		adapter = MagicMock()
		adapter.verify_payment_signature.return_value = False
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(
					team=TEAM,
					amount=5000,
					gateway=gw,
					razorpay_order_id="o",
					razorpay_payment_id="p",
					razorpay_signature="bad",
				)
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # no magic credit

	def test_topup_stripe_uses_inapp_payment_intent_and_confirms_via_intent(self):
		"""A Stripe (e.g. EUR) team gets an in-app PaymentIntent (no hosted-Checkout
		redirect), and the wallet is credited from the server-confirmed intent
		amount/currency — not INR, not a client-supplied figure."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway().name
		complete_billing_profile(TEAM)
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_stripe"
		adapter.create_order.return_value = {
			"client_secret": "pi_x_secret",
			"payment_intent_id": "pi_x",
			"publishable_key": "pk_test",
		}
		adapter.get_payment_intent.return_value = {
			"status": "succeeded",
			"id": "pi_x",
			"amount_received": 500000,
			"currency": "eur",
		}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, gateway=gw)
			self.assertEqual(order["adapter_key"], "Stripe")
			self.assertEqual(order["client_secret"], "pi_x_secret")  # in-app intent, not a redirect URL
			adapter.create_order.assert_called_once()
			# The intent is bound to the team's reused gateway customer.
			self.assertEqual(adapter.create_order.call_args.kwargs["customer"], "cus_stripe")
			self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # not credited yet

			out = dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw, payment_intent="pi_x")
			adapter.get_payment_intent.assert_called_once_with("pi_x")
			self.assertEqual(out["new_balance"], 5000)

	def test_topup_stripe_rejects_unsucceeded_intent(self):
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway().name
		adapter = MagicMock()
		adapter.get_payment_intent.return_value = {"status": "requires_payment_method", "id": "pi_y"}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw, payment_intent="pi_y")
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # no magic credit

	def test_topup_paypal_routes_to_paypal_gateway_and_captures(self):
		"""A USD team whose card default is Stripe can top up via PayPal: the order is
		routed to the PayPal gateway (directly settled, ADR 0007), and confirm captures
		the order — crediting PayPal's server-confirmed amount and keying the wallet
		entry on the capture id Finance reconciles against."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_paypal_adapter import make_paypal_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		stripe_def = make_stripe_gateway().name  # USD card default
		pp = make_paypal_gateway([("USD", 0)])  # handles USD, but is not its default
		complete_billing_profile(TEAM, currency="USD")
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_pp"
		adapter.create_order.return_value = {
			"order_id": "PPORDER1",
			"approve_url": "https://paypal/approve",
			"client_id": "pp_client",
		}
		adapter.capture_order.return_value = {
			"id": "CAP123",
			"status": "COMPLETED",
			"amount": "5000.00",
			"currency": "USD",
		}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, method="paypal")
			# Routed to a PayPal gateway, never the Stripe default.
			self.assertEqual(order["adapter_key"], "Paypal")
			self.assertNotEqual(order["gateway"], stripe_def)
			self.assertEqual(
				frappe.db.get_value("Payment Gateway", order["gateway"], "adapter_key"), "Paypal"
			)
			self.assertEqual(order["order_id"], "PPORDER1")
			self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # not credited yet

			out = dashboard.confirm_topup(team=TEAM, amount=5000, gateway=pp.name, paypal_order_id="PPORDER1")
			adapter.capture_order.assert_called_once_with("PPORDER1")
			self.assertEqual(out["new_balance"], 5000)
			# Wallet entry references the PayPal capture id (the reconcilable handle),
			# namespaced by provider.
			self.assertTrue(
				frappe.db.exists("Credit Ledger Entry", {"team": TEAM, "gateway_payment_id": "Paypal:CAP123"})
			)

	def test_topup_paypal_via_razorpay_delegates_to_razorpay(self):
		"""A PayPal gateway in 'Via Razorpay' mode holds no PayPal merchant account: the
		top-up is created on the currency's Razorpay gateway, the SPA is told to surface
		the PayPal block (display_paypal), and confirm settles through Razorpay — so the
		stored reference is the razorpay_payment_id (ADR 0005 path, opt-in)."""
		from unittest.mock import MagicMock, patch

		from central.billing.tests.test_paypal_adapter import make_paypal_gateway
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		make_razorpay_gateway([("USD", 0)])
		# There is one PayPal row, so putting it in Via-Razorpay mode IS the config —
		# no need to hunt down other enabled PayPal gateways that might win instead.
		pp = make_paypal_gateway([("USD", 0)], paypal_settlement_mode="Via Razorpay")
		self.assertTrue(pp.is_paypal_via_razorpay())
		self.assertFalse(pp._should_validate_credentials())  # keys optional in this mode
		complete_billing_profile(TEAM, currency="USD")
		adapter = MagicMock()
		adapter.create_customer.return_value = "cus_rzp"
		adapter.create_order.return_value = {"order_id": "order_rzp1", "key_id": "rzp_k"}
		adapter.verify_payment_signature.return_value = True
		adapter.get_payment.return_value = {"status": "captured", "amount": 500000, "currency": "USD"}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, method="paypal")
			# Settlement runs on a Razorpay gateway; the SPA opens the sheet on the
			# PayPal block (not PayPal Buttons, and never the PayPal row itself).
			self.assertEqual(order["adapter_key"], "Razorpay")
			self.assertEqual(
				frappe.db.get_value("Payment Gateway", order["gateway"], "adapter_key"), "Razorpay"
			)
			self.assertTrue(order["display_paypal"])
			out = dashboard.confirm_topup(
				team=TEAM,
				amount=5000,
				gateway=order["gateway"],
				razorpay_order_id="order_rzp1",
				razorpay_payment_id="pay_rzp1",
				razorpay_signature="sig",
			)
			self.assertEqual(out["new_balance"], 5000)
			# Reference is the razorpay_payment_id (no PayPal capture id exists here),
			# namespaced by provider.
			self.assertTrue(
				frappe.db.exists(
					"Credit Ledger Entry", {"team": TEAM, "gateway_payment_id": "Razorpay:pay_rzp1"}
				)
			)


class TestWriteEndpointsRejectGet(IntegrationTestCase):
	"""Every state-changing dashboard endpoint must be POST-only.

	A whitelisted method called over GET is NOT committed — Frappe's
	`sync_database()` rolls back any write unless the HTTP method is unsafe
	(POST/PUT/DELETE/PATCH). A wallet top-up confirmed over GET therefore booked
	a Credit Ledger Entry, returned 200 (the UI showed a success toast), then had
	the insert silently rolled back at end-of-request. Declaring these endpoints
	`methods=["POST"]` makes a stray GET fail loud (405) instead of losing money.
	This guards the whole write surface so the regression can't creep back in.
	"""

	def test_write_endpoints_are_post_only(self):
		from central.billing.api.dashboard import account, invoices, methods

		write_fns = [
			invoices.pay_invoice,
			invoices.create_topup_order,
			invoices.confirm_topup,
			methods.initiate_card_setup,
			methods.confirm_card,
			methods.add_demo_card,
			methods.setup_payment_method_order,
			methods.confirm_payment_method_order,
			methods.remove_payment_method,
			methods.set_default_payment_method,
			methods.reorder_payment_methods,
			account.save_billing_profile,
			account.save_billing_settings,
		]
		allowed = frappe.allowed_http_methods_for_whitelisted_func
		for fn in write_fns:
			with self.subTest(fn=fn.__name__):
				self.assertIn(fn, allowed, f"{fn.__name__} is not whitelisted")
				self.assertEqual(
					set(allowed[fn]),
					{"POST"},
					f"{fn.__name__} must be methods=['POST'] so a GET cannot silently roll back its writes",
				)


class TestPaymentMethodOptions(IntegrationTestCase):
	"""The customer picks an instrument and the instrument picks the gateway (ADR
	0023). Stripe takes everything a Stripe India account can carry; Razorpay takes
	what it cannot — all UPI, netbanking, and card mandates on RuPay, Amex and
	Diners. Recharge and mandate are separate surfaces with separate lists."""

	TEAM = "team-method-opts"

	def setUp(self):
		from central.billing.catalog.entitlements import recompute_trust_tier
		from central.billing.tests.test_entitlements import make_ladder
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway
		from central.billing.tests.utils import clear_team_tier

		ensure_team(self.TEAM)
		make_ladder()
		# One Stripe account carries both currencies: INR non-default (Razorpay owns
		# that currency's default), USD default.
		make_stripe_gateway([("INR", 0), ("USD", 1)])
		make_razorpay_gateway([("INR", 1)])
		complete_billing_profile(self.TEAM)
		frappe.db.set_value("Billing Profile", self.TEAM, "currency", "INR")
		clear_team_tier(self.TEAM)
		recompute_trust_tier(self.TEAM, paid_invoice_count=0, cumulative_paid=0)

	def test_india_offers_stripe_card_and_razorpay_upi(self):
		from central.billing.api.dashboard import methods

		out = methods.get_payment_method_options(self.TEAM)
		self.assertEqual(out["currency"], "INR")
		self.assertEqual(out["adapter_key"], "Stripe")  # Card rides Stripe, not Razorpay
		self.assertEqual(out["methods"], ["Card", "UPI Autopay"])  # Card is primary
		self.assertEqual(frappe.db.get_value("Payment Gateway", out["gateway"], "adapter_key"), "Stripe")
		self.assertTrue(out["publishable_key"])
		self.assertIn("allow_upi", out)  # UPI eligibility carried through

	def test_india_card_setup_uses_stripe_gateway(self):
		from unittest.mock import patch

		from central.billing.api.dashboard import methods

		captured = {}

		def fake_setup(team, gateway):
			captured["gateway"] = gateway
			return {"client_secret": "cs", "payment_method": "pm"}

		with patch("central.billing.payments.payments.initiate_payment_method_setup", fake_setup):
			methods.initiate_card_setup(self.TEAM)
		self.assertEqual(frappe.db.get_value("Payment Gateway", captured["gateway"], "adapter_key"), "Stripe")

	def test_the_mandate_surface_offers_three_tiles_on_the_right_rails(self):
		"""Stripe holds a mandate on Visa and Mastercard only, so everything else is
		Razorpay's — including UPI, which a Stripe India account cannot take at all."""
		from central.billing.api.dashboard import methods

		out = methods.get_payment_method_options(self.TEAM)
		rails = {t["instrument"]: t["adapter_key"] for t in out["instruments"]}
		self.assertEqual(
			rails,
			{"Card": "Stripe", "Other Network Card": "Razorpay", "UPI Autopay": "Razorpay"},
		)

	def test_netbanking_is_not_on_the_mandate_surface_at_all(self):
		"""It pays once and saves nothing. Offering it here is a promise we can't keep."""
		from central.billing.api.dashboard import methods

		out = methods.get_payment_method_options(self.TEAM)
		self.assertNotIn("Netbanking", [t["instrument"] for t in out["instruments"]])
		with self.assertRaises(frappe.ValidationError):
			methods.setup_payment_method_order(self.TEAM, instrument="Netbanking")

	def test_the_recharge_surface_is_a_different_list(self):
		from central.billing.api.dashboard import invoices

		out = invoices.get_topup_options(self.TEAM)
		rails = {t["instrument"]: t["adapter_key"] for t in out["instruments"]}
		self.assertEqual(
			rails,
			{
				"Card": "Stripe",
				"RuPay Card": "Razorpay",
				"UPI": "Razorpay",
				"Netbanking": "Razorpay",
			},
		)

	def test_tiles_name_their_networks_rather_than_saying_other(self):
		"""A customer holding an unusual Visa must never read a tile as theirs by
		accident, so no tile is labelled "Other cards"."""
		from central.billing.api.dashboard import methods

		labels = [t["label"] for t in methods.get_payment_method_options(self.TEAM)["instruments"]]
		self.assertIn("RuPay, Amex or Diners card", labels)
		self.assertNotIn("Other cards", labels)

	def test_a_card_top_up_goes_to_stripe_even_though_razorpay_owns_the_inr_default(self):
		from central.billing.payments import instruments

		self.assertEqual(instruments.gateway_for("Card", "INR", instruments.RECHARGE), "Stripe")
		self.assertEqual(instruments.gateway_for("UPI", "INR", instruments.RECHARGE), "Razorpay")

	def test_a_card_stripe_will_not_mandate_is_registered_on_razorpay(self):
		from central.billing.api.dashboard import methods
		from central.billing.tests.test_mandates import stub_adapter

		# The registration itself is a gateway round-trip, and a test must never make
		# one: the fixture's keys are dummies, so a real call authenticates as nobody.
		with stub_adapter():
			out = methods.setup_payment_method_order(self.TEAM, instrument="Other Network Card")
		method = frappe.get_doc("Payment Method", out["payment_method"])
		self.assertEqual(method.gateway, "Razorpay")
		self.assertEqual(method.fallback_reason, "Network Unsupported")

	def test_foreign_currency_is_stripe_card_only(self):
		from central.billing.api.dashboard import methods

		frappe.db.set_value("Billing Profile", self.TEAM, "currency", "USD")
		out = methods.get_payment_method_options(self.TEAM)
		self.assertEqual(out["adapter_key"], "Stripe")
		self.assertEqual(out["methods"], ["Card"])  # no UPI outside INR
		self.assertFalse(out["allow_upi"])
		self.assertEqual([t["instrument"] for t in out["instruments"]], ["Card"])
