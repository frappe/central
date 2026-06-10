# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Customer dashboard endpoints + forecast (issues #26, #18)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue import credits
from central.billing.api import dashboard
from central.billing.platform.sync import receive_usage_events
from central.billing.tests.utils import ensure_team, make_billing_team, make_plan, make_user

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
		make_plan(PLAN)
		self._purge()
		self.today = frappe.utils.getdate()
		self.month_start = frappe.utils.get_first_day(self.today)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Price Lock", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.commit()

	def _provision(self, rate=3000):
		receive_usage_events(
			[{"event_id": "ev-cust", "team": TEAM, "resource_id": "srv-cust", "cluster": CLUSTER,
			  "plan": PLAN, "shown_rate": rate, "currency": "INR", "event_type": "subscribed",
			  "effective_from": f"{self.month_start} 00:00:00", "effective_to": None}]
		)


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
		return frappe.get_doc(
			{"doctype": "Invoice", "team": TEAM, "invoice_type": "billable", "status": "Paid",
			 "period_start": "2026-05-01", "period_end": "2026-05-31", "currency": "INR",
			 "subtotal": 1000, "output_tax_type": "GST", "output_tax_amount": 180, "total": 1180,
			 "amount_paid": 1180,
			 "items": [{"resource_type": "bundle", "plan": PLAN, "rate": 1000, "days": 30, "amount": 1000}]}
		).insert(ignore_permissions=True).name

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

	def test_payment_methods_never_expose_secrets(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway("GW-Cust-Stripe").name
		frappe.get_doc(
			{"doctype": "Payment Method", "team": TEAM, "gateway": gw, "method_type": "card",
			 "status": "active", "display_label": "Visa ····4242", "gateway_method_id": "pm_secret",
			 "is_default": 1}
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
		self.assertEqual(ledger[0]["entry_type"], "credit")


class TestTeamScoping(CustomerDataBase):
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
		"""A team member whose role carries no billing capability (e.g. Viewer) —
		standing in for the role-less Agent key — gets a 403, view or mutate."""
		user = make_user()
		team = make_billing_team(user, role="Viewer")
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				dashboard.list_invoices(team.name)
			with self.assertRaises(frappe.PermissionError):
				dashboard.save_billing_settings(team=team.name, billing_mode="prepaid")
		finally:
			frappe.set_user("Administrator")


class TestCustomerActions(CustomerDataBase):
	def tearDown(self):
		if frappe.db.exists("Billing Profile", TEAM):
			frappe.db.delete("Billing Profile", {"team": TEAM})
		super().tearDown()

	def test_gstin_validation(self):
		dashboard.save_billing_profile(TEAM, legal_name="Acme Pvt Ltd", gstin="27AAPFU0939F1ZV")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "gstin"), "27AAPFU0939F1ZV")
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(TEAM, legal_name="Acme", gstin="NOT-A-GSTIN")


	def test_purchase_credits(self):
		out = dashboard.purchase_credits(team=TEAM, amount=1500)
		self.assertEqual(out["new_balance"], 1500)
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 1500)
		with self.assertRaises(frappe.ValidationError):
			dashboard.purchase_credits(team=TEAM, amount=0)


	def test_billing_settings_roundtrip(self):
		dashboard.save_billing_settings(team=TEAM, billing_mode="prepaid", min_balance=5000)
		s = dashboard.get_billing_settings(TEAM)
		self.assertEqual(s["billing_mode"], "prepaid")
		self.assertEqual(s["min_balance"], 5000)

	def test_admin_without_team_falls_back(self):
		from central.billing.catalog import subscriptions
		subscriptions.create_subscription(team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="monthly")
		invoices = dashboard.list_invoices()  # no team arg, as admin
		self.assertIsInstance(invoices, list)


class TestGatewayTopUp(CustomerDataBase):
	def test_topup_goes_through_gateway_and_verifies(self):
		from unittest.mock import MagicMock, patch
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway("GW-Cust-RZP").name
		adapter = MagicMock()
		adapter.create_order.return_value = {"order_id": "order_x", "key_id": "rzp_test", "amount": 500000}
		adapter.verify_payment_signature.return_value = True
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, gateway=gw)
			self.assertEqual(order["order_id"], "order_x")  # a real gateway order was created
			adapter.create_order.assert_called_once()
			# Wallet is NOT credited yet — only after the gateway confirms.
			self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)

			out = dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw,
				razorpay_order_id="order_x", razorpay_payment_id="pay_x", razorpay_signature="sig")
			adapter.verify_payment_signature.assert_called_once()
			self.assertEqual(out["new_balance"], 5000)

	def test_topup_rejects_bad_signature(self):
		from unittest.mock import MagicMock, patch
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		gw = make_razorpay_gateway("GW-Cust-RZP2").name
		adapter = MagicMock(); adapter.verify_payment_signature.return_value = False
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw,
					razorpay_order_id="o", razorpay_payment_id="p", razorpay_signature="bad")
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # no magic credit

	def test_topup_stripe_uses_hosted_checkout_and_confirms_via_session(self):
		"""A Stripe (e.g. EUR) team gets a hosted Checkout redirect, and the wallet
		is credited from the server-confirmed session amount/currency — not INR."""
		from unittest.mock import MagicMock, patch
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway("GW-Cust-Stripe-T").name
		adapter = MagicMock()
		adapter.create_checkout_session.return_value = {"checkout_url": "https://stripe.test/cs", "session_id": "cs_x"}
		adapter.get_checkout_session.return_value = {
			"payment_status": "paid", "payment_intent": "pi_x", "amount_total": 500000, "currency": "eur"}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = dashboard.create_topup_order(team=TEAM, amount=5000, gateway=gw)
			self.assertEqual(order["adapter_key"], "stripe")
			self.assertEqual(order["checkout_url"], "https://stripe.test/cs")  # redirect, not a Razorpay order
			adapter.create_checkout_session.assert_called_once()
			self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # not credited yet

			out = dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw, session="cs_x")
			adapter.get_checkout_session.assert_called_once_with("cs_x")
			self.assertEqual(out["new_balance"], 5000)

	def test_topup_stripe_rejects_unpaid_session(self):
		from unittest.mock import MagicMock, patch
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway("GW-Cust-Stripe-T2").name
		adapter = MagicMock()
		adapter.get_checkout_session.return_value = {"payment_status": "unpaid", "payment_intent": "pi_y"}
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(frappe.ValidationError):
				dashboard.confirm_topup(team=TEAM, amount=5000, gateway=gw, session="cs_y")
		self.assertEqual(dashboard.get_credit_balance(TEAM)["balance"], 0)  # no magic credit
