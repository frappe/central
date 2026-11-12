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


class OffSessionLimitBase(EmandateTestBase):
	"""A Beginner-tier INR team whose card mandate was registered at ₹8,300. The team may
	be charged off-session up to the largest amount any of its methods can take."""

	def setUp(self):
		from central.billing.tests.utils import set_team_tier

		super().setUp()
		set_team_tier(TEAM, level="t0", max_spend=8300)
		frappe.db.delete("Payment Method", {"team": TEAM})
		self.card = self._add_method("Card", 8300, priority=1)

	def _add_method(self, method_type, limit, priority):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": self.gw,
					"method_type": method_type,
					"status": "Active",
					"gateway_method_id": f"tok_{method_type}_{limit}",
					"gateway_customer_id": "cus",
					"mandate_max_amount": limit,
					"mandate_currency": "INR",
					"priority": priority,
					"validated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _mode(self):
		return frappe.db.get_value("Billing Profile", TEAM, "collection_mode")

	def _count(self, event_type):
		return frappe.db.count("Billing Notification Log", {"team": TEAM, "event_type": event_type})

	def _collect(self, inv):
		from unittest.mock import patch

		from central.billing.payments import collection

		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		return out, adapter


class TestOffSessionLimit(OffSessionLimitBase):
	def test_a_bill_equal_to_the_card_limit_is_noticed_and_charged(self):
		inv = self._invoice(8300)
		self.assertTrue(emandate.schedule_predebit(inv, now="2026-06-10 09:00:00").get("notified"))
		_out, adapter = self._collect(inv)
		adapter.charge.assert_called_once()
		self.assertEqual(self._mode(), "Auto Charge")

	def test_a_bill_over_the_card_limit_trips_at_notice_time(self):
		from central.billing.payments import collection_mode

		inv = self._invoice(9000)
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertEqual(out.get("skipped"), "over_threshold")
		self.assertEqual(self._mode(), "Action Required")
		self.assertIsNone(frappe.db.get_value("Invoice", inv, "predebit_notified_at"))
		self.assertEqual(self._count("Pre-debit Notice"), 0)
		self.assertEqual(self._count("Action Required"), 1)
		self.assertEqual(collection_mode.status(TEAM)["threshold"], 8300.0)

	def test_a_background_charge_over_the_card_limit_trips(self):
		from unittest.mock import patch

		from central.billing.payments import charges

		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = charges.pay_invoice(self._invoice(9000), payment_method=self.card, gateway=self.gw)
		self.assertEqual(out["reason"], "action_required")
		adapter.charge.assert_not_called()
		self.assertEqual(self._mode(), "Action Required")

	def test_the_pay_button_goes_to_checkout_without_tripping(self):
		from unittest.mock import MagicMock, patch

		from central.billing.api.dashboard import invoices

		inv = self._invoice(9000)
		adapter = _stub_adapter(self.gw)
		adapter.create_order = MagicMock(return_value={"order_id": "order_pay", "key_id": "rzp"})
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = invoices.pay_invoice(inv)
			order = invoices.pay_invoice_checkout(inv)
		self.assertEqual(out["reason"], "action_required")
		self.assertTrue(order["created"])
		adapter.charge.assert_not_called()
		self.assertEqual(self._mode(), "Auto Charge")
		self.assertEqual(self._count("Action Required"), 0)

	def test_a_bill_over_the_upi_limit_is_charged_on_the_card(self):
		frappe.db.set_value("Payment Method", self.card, "method_type", "UPI Autopay")
		card = self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		self.assertTrue(emandate.schedule_predebit(inv, now="2026-06-10 09:00:00").get("notified"))
		self._collect(inv)
		self.assertEqual(frappe.db.get_value("Payment Attempt", {"invoice": inv}, "payment_method"), card)
		self.assertEqual(self._mode(), "Auto Charge")

	def test_a_bill_left_with_only_a_too_small_method_trips(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection
		from central.billing.revenue import dunning

		frappe.db.set_value("Payment Method", self.card, "method_type", "UPI Autopay")
		card = self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		adapter = _stub_adapter(self.gw)
		adapter.charge = MagicMock(
			return_value=PaymentResult(success=False, status="Failed", failure_code="expired_card")
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		self.assertEqual(frappe.db.get_value("Payment Attempt", {"invoice": inv}, "payment_method"), card)
		adapter.charge.assert_called_once()
		self.assertEqual(self._mode(), "Action Required")
		self.assertFalse(dunning.has_retry_rail(frappe.get_doc("Invoice", inv), TEAM))

	def test_the_banner_and_the_notice_quote_the_limit_left_for_the_bill(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection, collection_mode
		from central.billing.platform import notifications

		frappe.db.set_value("Payment Method", self.card, "method_type", "UPI Autopay")
		self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		adapter = _stub_adapter(self.gw)
		adapter.charge = MagicMock(
			return_value=PaymentResult(success=False, status="Failed", failure_code="expired_card")
		)
		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch.object(notifications, "notify", wraps=notifications.notify) as notify,
		):
			collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		sent = [c for c in notify.call_args_list if c.args[1] == "Action Required"]
		self.assertEqual(len(sent), 1)
		self.assertEqual(sent[0].kwargs["context"]["threshold"], 8300.0)
		self.assertEqual(collection_mode.status(TEAM)["threshold"], 8300.0)

	def test_a_bill_over_every_limit_trips(self):
		self._add_method("Card", 15000, priority=2)
		inv = self._invoice(15001)
		out = emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		self.assertEqual(out.get("skipped"), "over_threshold")
		self.assertEqual(self._mode(), "Action Required")

	def test_an_over_limit_team_is_told_once_across_hourly_runs(self):
		from unittest.mock import patch

		from central.billing.payments import collection

		inv = self._invoice(9000)
		adapter = _stub_adapter(self.gw)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_invoice(inv, now="2026-06-10 09:00:00")
			collection.collect_invoice(inv, now="2026-06-10 11:00:00")
		adapter.charge.assert_not_called()
		self.assertEqual(self._count("Action Required"), 1)
		self.assertEqual(self._count("Add Payment Method"), 0)


class TestDunningRetryRail(OffSessionLimitBase):
	"""A Prepaid team with a ₹8,300 UPI first and a ₹15,000 card second, owing ₹9,000."""

	def setUp(self):
		super().setUp()
		_set_mode(TEAM, "Prepaid")
		frappe.db.set_value("Payment Method", self.card, "method_type", "UPI Autopay")
		self.upi = self.card

	def _charge(self, inv, result):
		from unittest.mock import MagicMock, patch

		from central.billing.revenue import dunning

		adapter = _stub_adapter(self.gw)
		if result:
			adapter.charge = MagicMock(return_value=result)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			dunning.retry_payment(inv)
		return adapter

	def _last_method(self, inv):
		return frappe.get_all(
			"Payment Attempt",
			filters={"invoice": inv},
			fields=["payment_method"],
			order_by="creation desc",
			limit=1,
		)[0].payment_method

	def test_a_soft_declined_card_is_retried_over_the_small_upi(self):
		from central.billing.gateways.base import PaymentResult
		from central.billing.revenue import dunning

		card = self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		declined = PaymentResult(
			success=False, status="Failed", failure_code="card_declined", decline_code="insufficient_funds"
		)
		self._charge(inv, declined)
		self.assertEqual(self._last_method(inv), card)
		self.assertEqual(self._mode(), "Prepaid")

		self.assertTrue(dunning.has_retry_rail(frappe.get_doc("Invoice", inv), TEAM))
		adapter = self._charge(inv, None)
		adapter.charge.assert_called_once()
		self.assertEqual(self._last_method(inv), card)
		self.assertFalse(frappe.db.exists("Payment Attempt", {"invoice": inv, "payment_method": self.upi}))

	def test_a_bill_nothing_covers_trips_and_leaves_no_retry(self):
		from central.billing.revenue import dunning

		self._add_method("Card", 8500, priority=2)
		inv = self._invoice(9000)
		self.assertTrue(dunning.has_retry_rail(frappe.get_doc("Invoice", inv), TEAM))
		adapter = self._charge(inv, None)
		adapter.charge.assert_not_called()
		self.assertEqual(self._mode(), "Action Required")
		self.assertFalse(dunning.has_retry_rail(frappe.get_doc("Invoice", inv), TEAM))


class TestChargingMethod(OffSessionLimitBase):
	"""The method the next-payment card names, and its own limit."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Payment Method", self.card, "method_type", "UPI Autopay")
		self.upi = self.card

	def _method(self, amount, invoice=None):
		from central.billing.api.dashboard import outlook

		return outlook._charging_method(TEAM, amount, invoice)

	def _label(self, method):
		return frappe.db.get_value("Payment Method", method, "display_label")

	def test_the_card_is_named_over_a_too_small_primary_upi(self):
		from central.billing.api import dashboard

		card = self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		out = dashboard.get_next_payment(TEAM)["method"]
		self.assertEqual(out["label"], self._label(card))
		self.assertEqual(out["ceiling"], 15000.0)
		self.assertEqual(self._method(9000, inv)["ceiling"], 15000.0)

	def test_the_primary_and_its_own_limit_when_nothing_covers(self):
		self._add_method("Card", 8500, priority=2)
		out = self._method(9000)
		self.assertEqual(out["label"], self._label(self.upi))
		self.assertEqual(out["ceiling"], 8300.0)

	def test_a_hard_declined_method_is_left_out(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection

		card = self._add_method("Card", 15000, priority=2)
		inv = self._invoice(9000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")
		adapter = _stub_adapter(self.gw)
		adapter.charge = MagicMock(
			return_value=PaymentResult(success=False, status="Failed", failure_code="expired_card")
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_invoice(inv, now="2026-06-11 10:00:00")
		self.assertEqual(self._method(9000)["label"], self._label(card))
		out = self._method(9000, inv)
		self.assertEqual(out["label"], self._label(self.upi))
		self.assertEqual(out["ceiling"], 8300.0)

	def test_a_method_off_session_cannot_reach_has_a_zero_limit(self):
		from unittest.mock import MagicMock, patch

		adapter = MagicMock(supports_off_session_charge=False)
		with patch("central.billing.gateways.registry.adapter_class", return_value=adapter):
			out = self._method(100)
		self.assertEqual(out["label"], self._label(self.upi))
		self.assertEqual(out["ceiling"], 0.0)

	def test_a_method_without_a_ceiling_has_no_limit(self):
		from unittest.mock import patch

		with patch("central.billing.gateways.capabilities.silent_charge_ceiling", return_value=None):
			frappe.db.set_value("Payment Method", self.upi, "mandate_max_amount", 0)
			out = self._method(50000)
		self.assertEqual(out["label"], self._label(self.upi))
		self.assertIsNone(out["ceiling"])
