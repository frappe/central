# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The credit a top-up reminder asks for: what the collector's draw needs, GST on top (#191)."""

from unittest.mock import MagicMock, patch

import frappe

from central.billing.payments import top_up_reminders
from central.billing.revenue import credits
from central.billing.revenue.invoicing import lifecycle, wallet_draw
from central.billing.tests.accounting_fake import billing_team
from central.billing.tests.test_top_up_reminders import _add_upi, _issued_invoice
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-top-up-credit"
BILL = 40000
# 40,000 with GST at 18%: 33,898.31 + 6,101.69.
NET = 33898.31
GST = 6101.69
TODAY = "2026-12-03"
PAYMENT_DATE = "2026-12-08"


class TopUpCreditTestCase(IntegrationTestCase):
	def setUp(self):
		billing_team(TEAM)  # Maharashtra, GST at 18%
		frappe.db.set_value("Billing Profile", TEAM, {"payment_day": 8, "collection_mode": "Prepaid"})
		frappe.db.delete("Payment Method", {"team": TEAM})
		_add_upi(TEAM)
		for target in (
			"central.billing.ingester.advance.enqueue_sync",
			"central.billing.ingester.erpnext_sync.enqueue_invoice_sync",
			"central.billing.payments.collection.collect_invoice",
		):
			self.enterContext(patch(target))
		# The company is in Karnataka unless a test says so; the team is in Maharashtra (IGST).
		self.enterContext(patch("central.billing.ingester.gst.cached_company_state_code", return_value="29"))
		# No test may reach a gateway.
		self.enterContext(patch("central.billing.gateways.registry.get_adapter", return_value=MagicMock()))

	def tearDown(self):
		for doctype in ("Billing Notification Log", "Team Notification", "Payment Method"):
			frappe.db.delete(doctype, {"team": TEAM})

	def _top_up(self, credit):
		"""A captured top-up of `credit`, paid with GST on top."""
		credits.purchase(
			TEAM,
			credit + credits.top_up_gst(TEAM, credit),
			"INR",
			gateway_payment_id=frappe.generate_hash(length=8),
			gateway="Stripe",
			credit=credit,
		)

	def _issue(self):
		invoice = _issued_invoice(TEAM, BILL, payment_date=PAYMENT_DATE)
		frappe.db.set_value("Invoice", invoice, {"subtotal": NET, "output_tax_amount": GST})
		return invoice

	def _due(self):
		return top_up_reminders.get_top_up_due(TEAM, TODAY)

	def _assert_it_settles(self, invoice, credit):
		"""₹100 less leaves the bill to the card; the credit asked for pays all of it."""
		self._top_up(credit - 100)
		self.assertEqual(lifecycle._settle_with_credit(invoice)["applied"], 0)
		self._top_up(100)
		self.assertEqual(lifecycle._settle_with_credit(invoice)["status"], "Paid")


class TestAnIssuedBillWithGst(TopUpCreditTestCase):
	def test_purchased_credit_pays_net_and_its_gst(self):
		"""5,000 credit (+900 GST) pays 5,900 of the bill. 34,100 is left: 28,898.31 of
		credit with its 5,201.69 GST, rounded up to 28,900, costing 34,102."""
		invoice = self._issue()
		self._top_up(5000)

		due = self._due()

		self.assertEqual((due["amount"], due["amount_with_gst"]), (28900, 34102))
		self._assert_it_settles(invoice, due["amount"])

	def test_promotional_credit_pays_the_bill_gst_included(self):
		"""5,000 promotional credit pays 5,000 of the bill. 35,000 is left: 29,661.02 of
		credit, rounded up to 29,700, costing 35,046."""
		invoice = self._issue()
		credits.grant_promotional_credits(TEAM, 5000, "INR", expires_on="2027-01-31")

		due = self._due()

		self.assertEqual((due["amount"], due["amount_with_gst"]), (29700, 35046))
		self._assert_it_settles(invoice, due["amount"])

	def test_the_message_names_both_figures(self):
		self._issue()
		self._top_up(5000)

		top_up_reminders.send_top_up_notice(TEAM, self._due())

		message = frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Top-up Reminder"}, "message"
		)
		self.assertIn(
			"Add ₹ 28,900.00 of credit to your wallet by 8 December 2026 (₹ 34,102.00 incl. IGST 18%). "
			"Your card or UPI pays only amounts up to ₹ 15,000.00.",
			message,
		)

	def test_a_same_state_team_is_told_cgst_and_sgst(self):
		self._issue()
		self._top_up(5000)

		with patch("central.billing.ingester.gst.cached_company_state_code", return_value="27"):
			due = self._due()
		top_up_reminders.send_top_up_notice(TEAM, due)

		self.assertEqual(top_up_reminders.format_due(due)["tax_label"], "CGST 9% + SGST 9%")
		message = frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Top-up Reminder"}, "message"
		)
		self.assertIn("(₹ 34,102.00 incl. CGST 9% + SGST 9%). ", message)


class TestTds(TopUpCreditTestCase):
	def test_a_tds_bill_asks_for_the_gst_the_collector_draws(self):
		"""With 677.97 TDS the collector draws 6,101.69 GST on 33,220.34 net, 18.37%, more
		than the 18% a top-up carries. So the 5,000 top-up's 900 GST runs short, and the
		credit must bring 5,201.69 of GST: 28,898.28, so 28,900. The ask is tight."""
		invoice = self._issue()
		frappe.db.set_value("Invoice", invoice, {"tds_amount": 677.97, "expected_collection": 39322.03})
		self._top_up(5000)

		due = self._due()

		self.assertEqual((due["amount"], due["amount_with_gst"]), (28900, 34102))
		self._assert_it_settles(invoice, due["amount"])


class TestGstBalanceBelowTheLots(TopUpCreditTestCase):
	def test_new_gst_pays_the_older_lot_first(self):
		"""A 5,000 top-up that brought only 450 GST pays 5,450. The new credit must bring
		the rest of the bill's GST, 5,651.69: 31,398.28, so 31,400. The ask is tight."""
		invoice = self._issue()
		credits.purchase(
			TEAM,
			5450,
			"INR",
			gateway_payment_id=frappe.generate_hash(length=8),
			gateway="Stripe",
			credit=5000,
		)

		due = self._due()

		self.assertEqual(due["amount"], 31400)
		self._assert_it_settles(invoice, due["amount"])


class TestABillNotIssuedYet(TopUpCreditTestCase):
	def test_the_forecast_is_read_with_gst(self):
		"""The same 40,000 forecast and 5,000 purchased credit ask for the same 28,900, and
		with it the wallet pays the whole bill when it is issued."""
		self._top_up(5000)
		with patch.object(top_up_reminders, "get_forecast_total", return_value=BILL):
			due = top_up_reminders.get_top_up_due(TEAM, "2026-11-26")

		self.assertEqual((due["amount"], due["amount_with_gst"], due["date"]), (28900, 34102, PAYMENT_DATE))
		self._top_up(due["amount"])
		invoice = _issued_invoice(TEAM, BILL, payment_date=PAYMENT_DATE)
		frappe.db.set_value("Invoice", invoice, {"subtotal": NET, "due_date": None, "payment_date": None})
		with self.freeze_time("2026-12-01 10:00:00"):
			result = lifecycle.open_and_collect(invoice)
		self.assertEqual(result["status"], "Paid")


class TestNoGst(TopUpCreditTestCase):
	def test_a_zero_rated_team_sees_one_figure(self):
		frappe.db.set_value("Tax Profile", TEAM, {"zero_rated": 1, "zero_rating_reason": "SEZ"})
		frappe.db.set_value("Billing Profile", TEAM, {"gstin": "27AAAAA0000A1Z5", "gst_status": "Active"})
		invoice = self._issue()
		frappe.db.set_value("Invoice", invoice, {"subtotal": BILL, "output_tax_amount": 0})
		credits.purchase(
			TEAM, 5000, "INR", gateway_payment_id=frappe.generate_hash(length=8), gateway="Stripe"
		)

		due = self._due()

		self.assertEqual((due["amount"], due["amount_with_gst"]), (35000, 35000))
		self.assertIsNone(top_up_reminders.format_due(due)["amount_with_gst"])
		top_up_reminders.send_top_up_notice(TEAM, due)
		message = frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Top-up Reminder"}, "message"
		)
		self.assertIn("Add ₹ 35,000.00 of credit to your wallet by 8 December 2026. Your card", message)
		self.assertNotIn("incl.", message)


class TestRounding(TopUpCreditTestCase):
	def test_the_credit_is_rounded_up_to_the_next_100(self):
		invoice = self._issue()
		frappe.db.set_value(
			"Invoice",
			invoice,
			{"total": 40001.18, "expected_collection": 40001.18, "output_tax_amount": 6101.87},
		)

		# 40,001.18 / 1.18 = 33,899.31, so 33,900.
		self.assertEqual(self._due()["amount"], 33900)

	def test_a_credit_short_by_a_paisa_steps_up(self):
		"""Here the credit that pays is 87,400.003. Rounded to 87,400 it leaves 0.01 owed
		after the collector rounds its draw, so the ask is 87,500."""
		lots = [
			frappe._dict(remaining=36982.96, paid_in=1),
			frappe._dict(remaining=24218.48, paid_in=1),
			frappe._dict(remaining=24978.49, paid_in=0),
		]
		ask = wallet_draw.TopUpAsk(lots, 191776.03, 20921.02, 11016.26, 0.18)

		self.assertEqual(ask.credit(100), 87500)
		self.assertFalse(ask.is_paid_with(87400))
		self.assertTrue(ask.is_paid_with(87500))

	def test_no_ask_when_no_credit_can_pay_the_bill(self):
		"""With no GST on a top-up but GST on the bill, purchased credit never pays the
		GST, so no amount is asked."""
		lots = [frappe._dict(remaining=5000.0, paid_in=1)]
		ask = wallet_draw.TopUpAsk(lots, 40000.0, 6101.69, 900.0, 0.0)

		self.assertIsNone(ask.credit(100))


EARLIER_GST_NOTE = "This includes GST on earlier credit that had none."


class TestEarlierCreditWithoutGst(TopUpCreditTestCase):
	def _message(self):
		top_up_reminders.send_top_up_notice(TEAM, self._due())
		return frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Top-up Reminder"}, "message"
		)

	def test_the_ask_says_it_carries_gst_for_earlier_credit(self):
		"""10,000 of purchased credit came with no GST. The new credit must bring all of the
		bill's 6,101.69 GST: 33,898.28, so 33,900, more than the 30,000 gap."""
		invoice = self._issue()
		credits.purchase(
			TEAM,
			10000,
			"INR",
			gateway_payment_id=frappe.generate_hash(length=8),
			gateway="Stripe",
			credit=10000,
		)

		due = self._due()

		self.assertEqual((due["amount"], due["amount_with_gst"]), (33900, 40002))
		self.assertTrue(due["includes_earlier_gst"])
		self.assertIn(
			"Add ₹ 33,900.00 of credit to your wallet by 8 December 2026 (₹ 40,002.00 incl. IGST 18%). "
			f"Your card or UPI pays only amounts up to ₹ 15,000.00. {EARLIER_GST_NOTE}",
			self._message(),
		)
		self._assert_it_settles(invoice, due["amount"])

	def test_purchased_credit_with_its_gst_says_nothing_more(self):
		self._issue()
		self._top_up(5000)

		self.assertFalse(self._due()["includes_earlier_gst"])
		self.assertNotIn(EARLIER_GST_NOTE, self._message())

	def test_a_tds_bill_with_credit_bought_with_its_gst_says_nothing_more(self):
		"""The TDS bill draws GST at 18.37%, so the new GST tops up the 5,000 lot, but that
		lot was bought with its 18% GST."""
		invoice = self._issue()
		frappe.db.set_value("Invoice", invoice, {"tds_amount": 677.97, "expected_collection": 39322.03})
		self._top_up(5000)

		self.assertFalse(self._due()["includes_earlier_gst"])
		self.assertNotIn(EARLIER_GST_NOTE, self._message())

	def test_promotional_credit_says_nothing_more(self):
		self._issue()
		credits.grant_promotional_credits(TEAM, 5000, "INR", expires_on="2027-01-31")

		self.assertFalse(self._due()["includes_earlier_gst"])
		self.assertNotIn(EARLIER_GST_NOTE, self._message())
