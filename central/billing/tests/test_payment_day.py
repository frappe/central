# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe

from central.billing import settings
from central.billing.api.dashboard import outlook
from central.billing.doctype.billing_profile.billing_profile import get_due_date, get_payment_date
from central.billing.gateways.base import PaymentResult
from central.billing.payments import collection, emandate, payment_notices
from central.billing.tests import test_emandate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = test_emandate.TEAM

PROFILE_TEAM = "team-payment-day"


class TestPaymentDayChanges(IntegrationTestCase):
	def setUp(self):
		ensure_team(PROFILE_TEAM)
		complete_billing_profile(PROFILE_TEAM)
		frappe.db.set_value(
			"Billing Profile",
			PROFILE_TEAM,
			{"payment_day": 1, "payment_day_changes": 0, "payment_day_changes_cycle": None},
		)

	def _change(self, day):
		profile = frappe.get_doc("Billing Profile", PROFILE_TEAM)
		profile.change_payment_day(day)
		profile.save(ignore_permissions=True)

	def test_a_day_after_the_10th_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._change(11)

	def test_a_team_changes_the_day_twice_in_a_cycle(self):
		with self.freeze_time("2026-11-05 10:00:00"):
			self._change(5)
			self._change(8)
			with self.assertRaises(frappe.ValidationError):
				self._change(3)

		self.assertEqual(frappe.db.get_value("Billing Profile", PROFILE_TEAM, "payment_day"), 8)

	def test_the_change_count_starts_again_in_the_next_cycle(self):
		with self.freeze_time("2026-11-05 10:00:00"):
			self._change(5)
			self._change(8)

		with self.freeze_time("2026-12-02 10:00:00"):
			self._change(3)

		self.assertEqual(frappe.db.get_value("Billing Profile", PROFILE_TEAM, "payment_day"), 3)

	def test_the_payment_date_is_the_payment_day_of_the_opening_month(self):
		frappe.db.set_value("Billing Profile", PROFILE_TEAM, "payment_day", 5)

		self.assertEqual(str(get_payment_date(PROFILE_TEAM, "2026-12-01")), "2026-12-05")
		# A run that opens the invoice late charges it the day it opens.
		self.assertEqual(str(get_payment_date(PROFILE_TEAM, "2026-12-07")), "2026-12-07")

	def test_an_invoice_is_not_due_before_its_payment_date(self):
		frappe.db.set_value("Billing Profile", PROFILE_TEAM, "payment_day", 10)

		with settings.overridden(invoice_due_days=7, dunning_retry_interval_days=2, suspension_day=15):
			self.assertEqual(str(get_due_date(PROFILE_TEAM, "2026-12-01")), "2026-12-10")
			ladder = outlook._escalation(PROFILE_TEAM, None, "2026-11-30")

		# A charge on the 10th has one retry, the next day, and the team is suspended on the 15th.
		self.assertEqual(
			[(row["stage"], row["date"]) for row in ladder[:3]],
			[
				("Retry", "2026-12-11"),
				("Overdue", "2026-12-11"),
				("Suspend", "2026-12-15"),
			],
		)


class TestDebitWaitsForThePaymentDate(test_emandate.EmandateTestBase):
	"""An Indian mandate gets its notice a day ahead, so the debit lands on the payment date."""

	def _invoice_due_on(self, payment_date):
		name = self._invoice(5000)
		frappe.db.set_value(
			"Invoice",
			name,
			{"payment_date": payment_date, "due_date": "2026-06-17", "suspends_on": "2026-06-24"},
		)
		return name

	def test_the_notice_waits_until_a_day_before_the_payment_date(self):
		name = self._invoice_due_on("2026-06-10")

		early = emandate.schedule_predebit(name, now="2026-06-08 09:00:00")
		self.assertEqual(early["skipped"], "before_payment_date")

		emandate.schedule_predebit(name, now="2026-06-09 01:00:00")
		charge_after = frappe.db.get_value("Invoice", name, "predebit_charge_after")
		self.assertEqual(str(charge_after), "2026-06-10 01:00:00")

	def test_the_sweep_charges_on_the_payment_date_once(self):
		name = self._invoice_due_on("2026-06-10")
		adapter = MagicMock()
		adapter.prepare_charge.return_value = None
		adapter.charge.return_value = PaymentResult(
			success=True, status="Captured", gateway_transaction_id="p"
		)

		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_on_payment_date(now="2026-06-09 01:00:00")
			self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)

			collection.collect_on_payment_date(now="2026-06-10 02:00:00")
			collection.collect_on_payment_date(now="2026-06-10 03:00:00")

		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 1)

	def test_a_rail_without_a_notice_waits_for_the_payment_date(self):
		name = self._invoice_due_on("2026-06-10")
		adapter = MagicMock()
		adapter.prepare_charge.return_value = None
		adapter.charge.return_value = PaymentResult(
			success=True, status="Captured", gateway_transaction_id="p"
		)

		with (
			patch.object(emandate, "is_notice_required", return_value=False),
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
		):
			before = collection.collect_invoice(name, now="2026-06-09 23:00:00")
			self.assertEqual(before["reason"], "before_payment_date")
			self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)

			collection.collect_invoice(name, now="2026-06-10 00:30:00")

		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 1)

	def test_an_open_invoice_without_a_payment_date_is_not_charged(self):
		name = self._invoice_due_on(None)

		with self.assertRaises(frappe.ValidationError):
			collection.collect_invoice(name, now="2026-06-10 00:30:00")

		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)

	def test_an_invoice_that_missed_its_payment_date_is_still_charged(self):
		name = self._invoice_due_on("2026-06-10")

		with (
			patch.object(emandate, "is_notice_required", return_value=False),
			patch("central.billing.gateways.registry.get_adapter", return_value=_capturing_adapter()),
		):
			collection.collect_on_payment_date(now="2026-06-20 02:00:00")

		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 1)

	def test_the_hourly_sweep_debits_a_mandate_once_its_window_opens(self):
		name = self._invoice_due_on("2026-06-10")
		emandate.schedule_predebit(name, now="2026-06-09 01:00:00")

		with (
			patch.object(emandate, "charge_due", wraps=emandate.charge_due) as charge_due,
			patch("central.billing.gateways.registry.get_adapter", return_value=_capturing_adapter()),
		):
			collection.collect_on_payment_date(now="2026-06-10 01:30:00")

		charge_due.assert_called_once()
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 1)


def _capturing_adapter() -> MagicMock:
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None
	adapter.charge.return_value = PaymentResult(success=True, status="Captured", gateway_transaction_id="p")
	return adapter


class TestPaymentReminder(test_emandate.EmandateTestBase):
	"""A day before the payment date the team hears what is charged, once."""

	def _invoice_due_on(self, payment_date):
		name = self._invoice(5000)
		frappe.db.set_value(
			"Invoice",
			name,
			{"payment_date": payment_date, "due_date": "2026-06-17", "suspends_on": "2026-06-24"},
		)
		return name

	def _reminders(self):
		return frappe.db.count("Billing Notification Log", {"team": TEAM, "event_type": "Payment Reminder"})

	def test_the_reminder_is_sent_once_the_day_before(self):
		name = self._invoice_due_on("2026-06-10")

		with patch.object(emandate, "is_notice_required", return_value=False):
			collection.collect_on_payment_date(now="2026-06-08 23:00:00")
			self.assertEqual(self._reminders(), 0)
			collection.collect_on_payment_date(now="2026-06-09 00:30:00")
			collection.collect_on_payment_date(now="2026-06-09 05:00:00")

		self.assertEqual(self._reminders(), 1)
		self.assertTrue(frappe.db.get_value("Invoice", name, "payment_reminder_sent_at"))
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)

	def test_an_invoice_settled_or_charged_after_selection_gets_no_reminder(self):
		now = frappe.utils.get_datetime("2026-06-09 00:30:00")
		name = self._invoice_due_on("2026-06-10")

		with patch.object(emandate, "is_notice_required", return_value=False):
			frappe.db.set_value("Invoice", name, "status", "Paid")
			self.assertEqual(payment_notices.send_payment_reminder(name, now)["skipped"], "not_due")

			frappe.db.set_value("Invoice", name, "status", "Outstanding")
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": name,
					"team": TEAM,
					"gateway": "Stripe",
					"amount": 5000,
					"currency": "INR",
					"status": "Initiated",
				}
			).insert(ignore_permissions=True)
			self.assertEqual(payment_notices.send_payment_reminder(name, now)["skipped"], "not_due")

		self.assertEqual(self._reminders(), 0)

	def test_a_sweep_that_overlaps_another_sends_no_second_reminder(self):
		now = frappe.utils.get_datetime("2026-06-09 00:30:00")
		name = self._invoice_due_on("2026-06-10")

		with patch.object(emandate, "is_notice_required", return_value=False):
			self.assertTrue(payment_notices.send_payment_reminder(name, now)["reminded"])
			# The second sweep read the invoice before the first one stamped it.
			with patch.object(payment_notices, "_is_reminder_due", return_value=True):
				result = payment_notices.send_payment_reminder(name, now)

		self.assertEqual(result["skipped"], "already_reminded")
		self.assertEqual(self._reminders(), 1)

	def test_the_reminder_follows_the_rail_of_the_method_that_is_charged(self):
		now = frappe.utils.get_datetime("2026-06-09 00:30:00")
		name = self._invoice_due_on("2026-06-10")
		# The team's own rail (Razorpay in USD) owes no notice. The charged mandate (in INR) does.
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")

		self.assertEqual(payment_notices.send_payment_reminder(name, now)["skipped"], "predebit_notice")

		frappe.db.delete("Payment Method", {"team": TEAM})
		self.assertTrue(payment_notices.send_payment_reminder(name, now)["reminded"])

	def test_the_reminder_names_the_amount_the_date_and_the_method(self):
		doc = frappe.get_doc("Invoice", self._invoice_due_on("2026-06-10"))

		context = payment_notices.get_payment_context(doc)

		self.assertEqual(set(context), {"amount", "payment_date", "method"})
		self.assertEqual(context["payment_date"], "10 June 2026")
		self.assertTrue(context["method"])

	def test_a_rail_with_a_predebit_notice_gets_no_reminder(self):
		name = self._invoice_due_on("2026-06-10")

		collection.collect_on_payment_date(now="2026-06-09 01:00:00")

		self.assertEqual(self._reminders(), 0)
		self.assertTrue(frappe.db.get_value("Invoice", name, "predebit_notified_at"))
		self.assertIsNone(frappe.db.get_value("Invoice", name, "payment_reminder_sent_at"))
