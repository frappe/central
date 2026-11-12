# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Off-session collection ≤₹15k: pre-debit notice → debit (ADR 0005, ADR 0022)."""

import frappe

from central.billing.payments import emandate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import clear_team_tier, complete_billing_profile, ensure_team

TEAM = "team-emandate"


def _set_mode(team, mode):
	doc = frappe.get_doc("Billing Profile", team)
	doc.collection_mode = mode
	doc.save(ignore_permissions=True)


class EmandateTestBase(IntegrationTestCase):
	"""An Auto Charge INR team with an active UPI Autopay mandate."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		_set_mode(TEAM, "Auto Charge")
		clear_team_tier(TEAM)
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		self.gw = make_razorpay_gateway().name
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": self.gw,
				"method_type": "UPI Autopay",
				"status": "Active",
				"gateway_method_id": "tok",
				"gateway_customer_id": "cus",
				"mandate_max_amount": 200000,
				"mandate_currency": "INR",
				"is_default": 1,
				"validated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

	def _invoice(self, amount):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Outstanding",
					"due_date": "2026-12-31",
					"payment_date": "2026-06-10",
					"suspends_on": "2027-01-15",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "INR",
					"subtotal": amount,
					"total": amount,
					"expected_collection": amount,
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": amount, "days": 30, "amount": amount}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestEmandatePredebit(EmandateTestBase):
	def test_schedule_predebit_notifies_and_arms_window(self):
		inv = self._invoice(5000)
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertTrue(out["notified"])
		row = frappe.db.get_value(
			"Invoice", inv, ["predebit_notified_at", "predebit_charge_after"], as_dict=True
		)
		self.assertIsNotNone(row.predebit_notified_at)
		# Debit window opens 24h after the notice.
		self.assertEqual(str(row.predebit_charge_after), "2026-06-11 09:00:00")
		self.assertTrue(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Pre-debit Notice"})
		)

	def test_a_prepaid_team_with_a_mandate_is_still_debited(self):
		_set_mode(TEAM, "Prepaid")
		out = emandate.schedule_predebit(self._invoice(5000), now="2026-06-10 09:00:00")
		self.assertTrue(out["notified"])

	def test_manual_checkout_is_never_debited(self):
		_set_mode(TEAM, "Manual Checkout")
		out = emandate.schedule_predebit(self._invoice(5000), now="2026-06-10 09:00:00")
		self.assertEqual(out["skipped"], "debit_not_allowed")

	def test_schedule_is_idempotent(self):
		inv = self._invoice(5000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		out = emandate.schedule_predebit(inv, now="2026-06-10 10:00:00")
		self.assertEqual(out["skipped"], "already_notified")
		self.assertEqual(
			frappe.db.count("Billing Notification Log", {"team": TEAM, "event_type": "Pre-debit Notice"}), 1
		)

	def test_over_threshold_forks_to_action_required_no_notice(self):
		inv = self._invoice(20000)  # over ₹15k — can't be debited silently
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertTrue(out.get("action_required"))
		self.assertIsNone(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Action Required")
		# No pre-debit notice was sent for a debit we can't make.
		self.assertFalse(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Pre-debit Notice"})
		)

	def test_a_prepaid_remainder_over_threshold_moves_to_action_required_no_notice(self):
		_set_mode(TEAM, "Prepaid")
		inv = self._invoice(20000)  # what is left after the wallet, over ₹15k
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertTrue(out.get("action_required"))
		self.assertIsNone(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Action Required")
		self.assertFalse(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Pre-debit Notice"})
		)
		self.assertTrue(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Action Required"})
		)

	def test_charge_due_only_after_window(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult

		inv = self._invoice(5000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")  # window opens 06-11 09:00

		adapter = MagicMock()
		adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
		adapter.charge.return_value = PaymentResult(
			success=True, status="Captured", gateway_transaction_id="pay_e"
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			# Before the window: nothing charged.
			early = emandate.charge_due(now="2026-06-11 08:00:00")
			self.assertEqual(early, [])
			self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 0)

			# After the window: the off-session debit runs (one attempt).
			late = emandate.charge_due(now="2026-06-11 10:00:00")
			self.assertEqual(len(late), 1)
			adapter.charge.assert_called_once()
			self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 1)

	def test_charge_due_reads_the_window_on_the_clock_it_is_given(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult

		inv = self._invoice(5000)
		frappe.db.set_value("Invoice", inv, "payment_date", "2099-06-11")
		out = emandate.schedule_predebit(inv, now="2099-06-10 09:00:00")
		self.assertTrue(out.get("notified"))
		# The debit waits 24 hours after the notice, which is later than the payment date start.
		self.assertEqual(out["charge_after"], "2099-06-11 09:00:00")

		adapter = MagicMock()
		adapter.prepare_charge.return_value = None
		adapter.charge.return_value = PaymentResult(
			success=True, status="Captured", gateway_transaction_id="p"
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			emandate.charge_due(now="2099-06-11 10:00:00")
		# charge_due reads the whole site, so count only this invoice's charge.
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 1)

	def test_an_exhausted_mandate_is_asked_for_another_method_once(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection

		inv = self._invoice(5000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")  # window opens 06-11 09:00

		adapter = MagicMock()
		adapter.prepare_charge.return_value = None
		adapter.charge.return_value = PaymentResult(
			success=False, status="Failed", failure_code="card_declined", failure_reason="declined"
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_on_payment_date(now="2026-06-11 10:00:00")
			collection.collect_on_payment_date(now="2026-06-11 12:00:00")

		adapter.charge.assert_called_once()
		asks = {"team": TEAM, "event_type": "Add Payment Method", "reference_name": inv}
		self.assertEqual(frappe.db.count("Billing Notification Log", asks), 1)


class TestWhoOwesAPredebitNotice(IntegrationTestCase):
	"""The notice follows the rail, not the mode. Every auto-charged team is now
	`Auto Charge`, so a USD card must not be delayed 24h for a notice nobody in that
	currency is owed (ADR 0022)."""

	TEAM = "team-predebit-rail"

	def setUp(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		ensure_team(self.TEAM)
		complete_billing_profile(self.TEAM, currency="USD")
		_set_mode(self.TEAM, "Auto Charge")
		frappe.db.delete("Invoice", {"team": self.TEAM})
		make_stripe_gateway()

	def test_a_usd_card_team_is_left_to_the_ordinary_sweep(self):
		inv = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": self.TEAM,
					"invoice_type": "Billable",
					"status": "Outstanding",
					"payment_date": "2026-07-01",
					"due_date": "2026-12-31",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "USD",
					"subtotal": 500,
					"total": 500,
					"expected_collection": 500,
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": 500, "days": 30, "amount": 500}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertEqual(out["skipped"], "no_notice_required")
		self.assertIsNone(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))


def _stub_adapter(gateway: str):
	"""The real Razorpay adapter, so its ceiling check runs, with every gateway call faked."""
	from unittest.mock import MagicMock

	from central.billing.gateways.base import PaymentResult
	from central.billing.gateways.razorpay_adapter import RazorpayAdapter

	adapter = RazorpayAdapter(frappe.get_doc("Payment Gateway", gateway))
	adapter.prepare_charge = MagicMock(return_value=None)
	adapter.charge = MagicMock(
		return_value=PaymentResult(success=True, status="Captured", gateway_transaction_id="pay_c")
	)
	return adapter


class TestGatewayCeilingOnly(EmandateTestBase):
	"""A Beginner-tier Prepaid team: the trust-tier cap never trips a debit, only the
	₹15,000 ceiling does, and an amount equal to it is allowed."""

	def setUp(self):
		from central.billing.tests.utils import set_team_tier

		super().setUp()
		_set_mode(TEAM, "Prepaid")
		set_team_tier(TEAM, level="t0", max_spend=8300)

	def _mode(self):
		return frappe.db.get_value("Billing Profile", TEAM, "collection_mode")

	def _pay(self, inv):
		from unittest.mock import patch

		from central.billing.payments import charges

		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			return charges.pay_invoice(inv, payment_method=self._method(), gateway=self.gw), adapter

	def _method(self):
		return frappe.db.get_value("Payment Method", {"team": TEAM}, "name")

	def test_a_remainder_over_the_tier_cap_gets_a_notice(self):
		out = emandate.schedule_predebit(self._invoice(9000), now="2026-06-10 09:00:00")
		self.assertTrue(out.get("notified"))
		self.assertEqual(self._mode(), "Prepaid")

	def test_a_remainder_equal_to_the_ceiling_gets_a_notice(self):
		out = emandate.schedule_predebit(self._invoice(15000), now="2026-06-10 09:00:00")
		self.assertTrue(out.get("notified"))
		self.assertEqual(self._mode(), "Prepaid")

	def test_a_remainder_over_the_ceiling_trips_at_notice_time(self):
		out = emandate.schedule_predebit(self._invoice(15001), now="2026-06-10 09:00:00")
		self.assertEqual(out.get("skipped"), "over_threshold")
		self.assertEqual(self._mode(), "Action Required")

	def test_a_remainder_equal_to_the_ceiling_is_charged(self):
		out, adapter = self._pay(self._invoice(15000))
		self.assertNotEqual(out.get("reason"), "action_required")
		adapter.charge.assert_called_once()
		self.assertEqual(self._mode(), "Prepaid")

	def test_a_remainder_over_the_ceiling_trips_at_charge_time(self):
		out, adapter = self._pay(self._invoice(15001))
		self.assertEqual(out["reason"], "action_required")
		adapter.charge.assert_not_called()
		self.assertEqual(self._mode(), "Action Required")

	def test_the_banner_shows_the_ceiling_it_tripped_at(self):
		from central.billing.payments import collection_mode

		emandate.schedule_predebit(self._invoice(15001), now="2026-06-10 09:00:00")
		self.assertEqual(collection_mode.status(TEAM)["threshold"], 15000.0)


class TestMandateLimit(EmandateTestBase):
	"""A UPI mandate registered at the tier cap cannot take more than that, so the
	collector skips it rather than tripping Action Required."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Payment Method", {"team": TEAM}, "mandate_max_amount", 8300)

	def test_no_notice_when_no_mandate_can_take_the_amount(self):
		inv = self._invoice(9000)
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertEqual(out.get("skipped"), "over_mandate_limit")
		self.assertIsNone(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Auto Charge")

	def test_the_collector_skips_the_mandate_and_asks_for_another_method(self):
		from unittest.mock import patch

		from central.billing.payments import collection

		inv = self._invoice(9000)
		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		self.assertEqual(out["reason"], "no_method")
		adapter.charge.assert_not_called()
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Auto Charge")
		asks = {"team": TEAM, "event_type": "Add Payment Method", "reference_name": inv}
		self.assertEqual(frappe.db.count("Billing Notification Log", asks), 1)

	def test_the_collector_moves_on_to_a_method_that_can_take_it(self):
		from unittest.mock import patch

		from central.billing.payments import collection

		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": self.gw,
				"method_type": "Card",
				"status": "Active",
				"gateway_method_id": "tok_card",
				"gateway_customer_id": "cus",
				"mandate_max_amount": 1000000,
				"mandate_currency": "INR",
				"priority": 2,
				"validated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		inv = self._invoice(9000)
		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		# The card is on a notice rail, so it gets the notice the mandate could not.
		self.assertEqual(out.get("reason"), "awaiting_predebit_window")
		self.assertTrue(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))
		adapter.charge.assert_not_called()
