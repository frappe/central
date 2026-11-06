# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.payments import payment_notices
from central.billing.revenue import invoicing
from central.billing.tests import test_emandate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team, give_team_a_card

TEAM = "team-payment-notices"


def _logs(event_type: str) -> list[frappe._dict]:
	return frappe.get_all(
		"Billing Notification Log",
		filters={"team": TEAM, "event_type": event_type},
		fields=["message", "reference_name"],
	)


def _draft(team: str, total=5000) -> str:
	"""A billable draft the run has not opened yet."""
	return (
		frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": team,
				"invoice_type": "Billable",
				"status": "Outstanding",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
				"currency": "INR",
				"subtotal": total,
				"total": total,
				"expected_collection": total,
				"items": [
					{"resource_type": "bundle", "plan": "p", "rate": total, "days": 31, "amount": total}
				],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _scheduled(team: str) -> list[frappe._dict]:
	return frappe.get_all(
		"Billing Notification Log",
		filters={"team": team, "event_type": "Payment Scheduled"},
		fields=["message", "reference_name"],
	)


class TestPaymentScheduled(IntegrationTestCase):
	"""When the run opens an invoice with an amount left after credit, the team hears what is
	charged and when."""

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, "payment_day", 5)
		frappe.db.delete("Billing Notification Log", {"team": TEAM})

	def _open(self, invoice):
		with self.freeze_time("2026-11-01 10:00:00"):
			return invoicing.open_and_collect(invoice)

	def test_a_card_is_charged_on_the_payment_date(self):
		give_team_a_card(TEAM)
		invoice = _draft(TEAM)

		self._open(invoice)

		logs = _scheduled(TEAM)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].reference_name, invoice)
		self.assertIn("5 November 2026", logs[0].message)

	def test_opening_again_sends_nothing_more(self):
		invoice = _draft(TEAM)

		self._open(invoice)
		self.assertFalse(self._open(invoice)["claimed"])

		self.assertEqual(len(_scheduled(TEAM)), 1)

	def test_a_team_without_a_method_is_asked_to_add_one(self):
		self._open(_draft(TEAM))

		self.assertIn("Add a payment method", _scheduled(TEAM)[0].message)

	def test_a_held_invoice_sends_no_schedule(self):
		frappe.db.set_value("Billing Profile", TEAM, "legal_name", None)

		self.assertTrue(self._open(_draft(TEAM)).get("held"))
		self.assertEqual(_scheduled(TEAM), [])


class TestPaymentScheduledOnAMandate(test_emandate.EmandateTestBase):
	"""A mandate is debited 24 hours after its pre-debit notice, so the schedule names that day."""

	def test_an_invoice_opened_on_its_payment_date_names_the_debit_day(self):
		frappe.db.set_value("Billing Profile", test_emandate.TEAM, "payment_day", 1)
		invoice = _draft(test_emandate.TEAM)

		with self.freeze_time("2026-12-01 10:00:00"):
			invoicing.open_and_collect(invoice)

		logs = _scheduled(test_emandate.TEAM)
		self.assertEqual(len(logs), 1)
		self.assertIn("2 December 2026", logs[0].message)


class TestPaymentDateChanged(IntegrationTestCase):
	"""A new payment day is confirmed, with the invoice it applies to."""

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.set_value(
			"Billing Profile",
			TEAM,
			{"payment_day": 1, "payment_day_changes": 0, "payment_day_changes_cycle": None},
		)
		frappe.db.delete("Billing Notification Log", {"team": TEAM})

	def _save_day(self, day):
		profile = frappe.get_doc("Billing Profile", TEAM)
		profile.payment_day = day
		profile.save(ignore_permissions=True)

	def test_a_new_payment_day_is_confirmed_with_the_next_payment_date(self):
		with self.freeze_time("2026-11-05 10:00:00"):
			self._save_day(5)

		logs = _logs("Payment Date Changed")
		self.assertEqual(len(logs), 1)
		self.assertIn("5th", logs[0].message)
		self.assertIn("5 December 2026", logs[0].message)

	def test_an_issued_invoice_keeps_its_payment_date(self):
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Outstanding",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
				"currency": "INR",
				"total": 5000,
				"expected_collection": 5000,
				"payment_date": "2026-11-08",
				"due_date": "2026-11-08",
			}
		).insert(ignore_permissions=True)

		with self.freeze_time("2026-11-05 10:00:00"):
			self._save_day(3)

		message = _logs("Payment Date Changed")[0].message
		self.assertIn(invoice.name, message)
		self.assertIn("8 November 2026", message)

	def test_a_save_that_keeps_the_day_sends_nothing(self):
		self._save_day(1)

		self.assertEqual(_logs("Payment Date Changed"), [])

	def test_the_ordinal_reads_like_a_date(self):
		days = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 11: "11th", 12: "12th", 13: "13th", 21: "21st"}
		for day, ordinal in days.items():
			self.assertEqual(payment_notices.get_ordinal(day), ordinal)
