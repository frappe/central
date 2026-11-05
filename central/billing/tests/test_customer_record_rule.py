# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A team gets accounting records only when it has something to account for."""

from unittest.mock import patch

import frappe

from central.billing.ingester import customer
from central.billing.revenue import credits, invoicing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-customer-rule"
CLUSTER = "ap-south-1"
PLAN = "bundle-customer-rule"


def _sync_on():
	return patch("central.billing.ingester.customer.enabled", return_value=True)


class TestCustomerRecordRule(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		self.profile = frappe.get_doc("Billing Profile", TEAM)

	def test_a_complete_profile_alone_creates_no_customer(self):
		with _sync_on():
			self.assertFalse(customer._should_sync(self.profile))
			self.assertNotIn(TEAM, customer._pending_teams())

	def test_an_enabled_subscription_creates_the_customer(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		frappe.db.set_value("Subscription", subscription, "enabled", 1)

		with _sync_on():
			self.assertTrue(customer._should_sync(self.profile))

	def test_enabling_a_subscription_queues_the_sync(self):
		make_plan(PLAN)
		name = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		subscription = frappe.get_doc("Subscription", name)
		subscription.flags.ignore_validate = True
		subscription.enabled = 1

		with patch("central.billing.ingester.customer.enqueue_for") as enqueue:
			subscription.save(ignore_permissions=True)

		enqueue.assert_called_once_with(TEAM)

	def test_a_paid_top_up_creates_the_customer(self):
		with patch("central.billing.ingester.advance.enqueue_sync"):
			credits.purchase(TEAM, 100, "INR", gateway="Stripe", gateway_payment_id="pay_customer_rule")

		with _sync_on():
			self.assertTrue(customer._should_sync(self.profile))

	def test_free_credit_alone_creates_no_customer(self):
		credits.grant_promotional_credits(TEAM, 100, "INR")

		with _sync_on():
			self.assertFalse(customer._should_sync(self.profile))

	def test_a_cancelled_subscription_with_an_unpaid_invoice_keeps_its_customer(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		invoicing.generate_draft_invoice(subscription, "2026-06-01", "2026-06-30")

		with _sync_on():
			self.assertTrue(customer._should_sync(self.profile))


class TestWaivedInvoiceAccounting(IntegrationTestCase):
	def test_a_waived_invoice_never_needs_syncing(self):
		make_plan(PLAN)
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, {"is_internal": 1, "internal_reason": "Ours"})
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		invoice = invoicing.generate_draft_invoice(subscription, "2026-06-01", "2026-06-30")

		invoicing.open_and_collect(invoice)

		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Waived")
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "erpnext_sync_status"), "Not Required")
