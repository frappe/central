# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""E-mandate ≤₹15k off-session collection: pre-debit notice → debit (#50 item 3, ADR 0005)."""

import frappe

from central.billing.payments import emandate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import clear_team_tier, complete_billing_profile, ensure_team

TEAM = "team-emandate"


def _set_mode(team, mode):
	doc = frappe.get_doc("Billing Profile", team)
	doc.collection_mode = mode
	doc.save(ignore_permissions=True)


class TestEmandatePredebit(IntegrationTestCase):
	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		_set_mode(TEAM, "E-Mandate")
		clear_team_tier(TEAM)
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		self.gw = make_razorpay_gateway("GW-Emandate-RZP").name
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
					"status": "Open",
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

	def test_charge_due_only_after_window(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult

		inv = self._invoice(5000)
		emandate.schedule_predebit(inv, now="2026-06-10 09:00:00")  # window opens 06-11 09:00

		adapter = MagicMock()
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
