# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe

from central.billing import settings
from central.billing.api.dashboard import outlook
from central.billing.doctype.billing_profile.billing_profile import get_due_date, get_payment_date
from central.billing.gateways.base import PaymentResult
from central.billing.payments import collection, emandate
from central.billing.revenue.dunning import dunning_schedule
from central.billing.tests import test_emandate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

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

		with settings.overridden(invoice_due_days=7):
			self.assertEqual(str(get_due_date(PROFILE_TEAM, "2026-12-01")), "2026-12-10")
			ladder = outlook._escalation(PROFILE_TEAM, None, "2026-11-30")

		self.assertEqual(ladder[0]["date"], str(dunning_schedule("2026-12-10")[0].date))


class TestDebitWaitsForThePaymentDate(test_emandate.EmandateTestBase):
	"""An Indian mandate gets its notice a day ahead, so the debit lands on the payment date."""

	def _invoice_due_on(self, payment_date):
		name = self._invoice(5000)
		frappe.db.set_value("Invoice", name, {"payment_date": payment_date, "due_date": "2026-06-17"})
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
