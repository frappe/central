# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment notices say whether their amounts include tax, and name it (#193 part B)."""

from unittest.mock import MagicMock, patch

import frappe

from central.billing.payments import collection_mode, emandate, payment_notices
from central.billing.platform import notifications
from central.billing.tests import test_emandate
from central.billing.tests.test_tax_labels import COMPANY_STATE, TEAM, TaxLabelTestCase, _invoice, _set_gst
from central.billing.tests.utils import complete_billing_profile, give_team_a_card


def _message(team: str, event_type: str) -> str:
	rows = frappe.get_all(
		"Billing Notification Log",
		filters={"team": team, "event_type": event_type},
		pluck="message",
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else ""


class TestNoticesNameTheTax(TaxLabelTestCase):
	def _remind(self, invoice: str) -> str:
		doc = frappe.get_doc("Invoice", invoice)
		notifications.notify(
			TEAM,
			"Payment Reminder",
			context=payment_notices.get_payment_context(doc),
			reference_doctype="Invoice",
			reference_name=invoice,
		)
		return _message(TEAM, "Payment Reminder")

	def test_igst(self):
		self._move_to("Karnataka")
		self.assertIn("₹ 11,800.00 (incl. IGST 18%)", self._remind(_invoice(TEAM)))

	def test_cgst_and_sgst(self):
		self.assertIn("₹ 11,800.00 (incl. CGST 9% + SGST 9%)", self._remind(_invoice(TEAM)))

	def test_sez(self):
		self.assertIn("₹ 10,000.00 (SEZ supply, no GST)", self._remind(_invoice(TEAM, sez=True)))

	def test_outside_india_names_no_tax(self):
		complete_billing_profile(TEAM, currency="USD")
		frappe.db.delete("Tax Profile", {"team": TEAM})
		message = self._remind(_invoice(TEAM, rate=0, currency="USD"))
		self.assertNotIn("(incl.", message)
		self.assertNotIn("GST", message)

	def test_the_scheduled_notice_names_the_tax_on_the_total_and_the_charge(self):
		give_team_a_card(TEAM)
		with patch("central.billing.gateways.registry.get_adapter", return_value=MagicMock()):
			payment_notices.notify_payment_scheduled(frappe.get_doc("Invoice", _invoice(TEAM)))

		message = _message(TEAM, "Payment Scheduled")
		self.assertIn("totals ₹ 11,800.00 (incl. CGST 9% + SGST 9%).", message)
		self.assertIn("We'll charge ₹ 11,800.00 (incl. CGST 9% + SGST 9%) to", message)

	def test_action_required_names_the_tax_the_limit_applies_to(self):
		self._move_to("Karnataka")
		give_team_a_card(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Auto Charge")

		collection_mode.trip(TEAM, "invoice_over_threshold")

		self.assertIn("up to ₹ 15,000.00 (incl. IGST 18%).", _message(TEAM, "Action Required"))

	def test_action_required_for_an_sez_team_names_no_tax_on_the_limit(self):
		_set_gst(TEAM, zero_rated=1, zero_rating_reason="SEZ")
		give_team_a_card(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Auto Charge")

		collection_mode.trip(TEAM, "invoice_over_threshold")

		message = _message(TEAM, "Action Required")
		self.assertIn("up to ₹ 15,000.00.", message)
		self.assertNotIn("SEZ", message)


class TestPredebitNoticeShowsTheAmount(test_emandate.EmandateTestBase):
	def setUp(self):
		super().setUp()
		_set_gst(test_emandate.TEAM)
		frappe.db.set_value("Billing Profile", test_emandate.TEAM, "state", "Karnataka")
		self.enterContext(
			patch("central.billing.ingester.gst.cached_company_state_code", return_value=COMPANY_STATE)
		)

	def tearDown(self):
		for doctype in ("Tax Profile", "Billing Notification Log", "Team Notification"):
			frappe.db.delete(doctype, {"team": test_emandate.TEAM})

	def test_the_notice_names_the_amount_with_its_gst(self):
		invoice = _invoice(test_emandate.TEAM, payment_date="2026-06-10")

		self.assertTrue(emandate.schedule_predebit(invoice, now="2026-06-10 09:00:00")["notified"])

		message = _message(test_emandate.TEAM, "Pre-debit Notice")
		self.assertIn(f"We'll auto-debit ₹ 11,800.00 (incl. IGST 18%) for invoice {invoice}", message)
