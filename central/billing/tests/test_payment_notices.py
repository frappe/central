# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.payments import payment_notices
from central.billing.platform.records import save_billing_record
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team, give_team_a_card

TEAM = "team-payment-notices"


def _logs(event_type: str) -> list[frappe._dict]:
	return frappe.get_all(
		"Billing Notification Log",
		filters={"team": TEAM, "event_type": event_type},
		fields=["message", "reference_name"],
	)


class TestPaymentScheduled(IntegrationTestCase):
	"""When an invoice opens with an amount left after credit, the team hears what is charged and when."""

	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.delete("Billing Notification Log", {"team": TEAM})

	def _draft(self, total=5000, credit=1000):
		return frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Outstanding",
				"period_start": "2026-10-01",
				"period_end": "2026-10-31",
				"currency": "INR",
				"subtotal": total,
				"total": total,
				"credit_applied": credit,
				"expected_collection": total - credit,
			}
		).insert(ignore_permissions=True)

	def _open(self, doc):
		doc.payment_date = "2026-11-05"
		doc.due_date = "2026-11-08"
		save_billing_record(doc)

	def test_opening_an_invoice_sends_the_schedule_once(self):
		give_team_a_card(TEAM)
		doc = self._draft()

		self._open(doc)
		doc.reload()
		save_billing_record(doc)

		logs = _logs("Payment Scheduled")
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].reference_name, doc.name)
		for part in ("5,000.00", "1,000.00", "4,000.00", "5 November 2026"):
			self.assertIn(part, logs[0].message)

	def test_a_team_without_a_method_is_asked_to_add_one(self):
		self._open(self._draft())

		self.assertIn("Add a payment method", _logs("Payment Scheduled")[0].message)

	def test_an_invoice_credit_paid_in_full_sends_no_schedule(self):
		doc = self._draft(credit=5000)
		doc.status = "Paid"
		self._open(doc)

		self.assertEqual(_logs("Payment Scheduled"), [])

	def test_a_draft_that_stays_unissued_sends_no_schedule(self):
		doc = self._draft()
		doc.hold_reason = "Billing Details"
		save_billing_record(doc)

		self.assertEqual(_logs("Payment Scheduled"), [])


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
