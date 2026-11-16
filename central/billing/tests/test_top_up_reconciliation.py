# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.payments import reconciliation
from central.billing.tests.test_reconciliation import GATEWAY, TEAM, ReconTestBase, gateway_status


class TestTopUpReconciliation(ReconTestBase):
	"""A top-up whose callback and webhook were both lost is credited from the gateway."""

	def _order(self, order_id, hours_old=1):
		from central.billing.doctype.top_up_order.top_up_order import TopupOrder

		order = TopupOrder.start(TEAM, GATEWAY, "INR", 700, credit=700)
		order.record_gateway_order(order_id)
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-hours_old)
		frappe.db.set_value("Top-up Order", order.name, "creation", old, update_modified=False)
		return order.name

	def test_a_paid_top_up_is_credited(self):
		from central.billing.gateways.base import VerifiedPayment
		from central.billing.revenue import credits

		order = self._order("pi_lost")
		with gateway_status("succeeded") as adapter:
			adapter.find_order_payment.return_value = VerifiedPayment(
				"pi_lost", True, 700, "INR", order_id="pi_lost"
			)
			reconciliation.reconcile_top_up_orders()
		self.assertEqual(frappe.db.get_value("Top-up Order", order, "status"), "Credited")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 700)

	def test_a_short_top_up_fails_without_stopping_the_run(self):
		from central.billing.gateways.base import VerifiedPayment

		short = self._order("pi_short")
		paid = self._order("pi_paid")
		with gateway_status("succeeded") as adapter:
			adapter.find_order_payment.side_effect = lambda order_id: VerifiedPayment(
				order_id, True, 100 if order_id == "pi_short" else 700, "INR", order_id=order_id
			)
			reconciliation.reconcile_top_up_orders()

		self.assertEqual(frappe.db.get_value("Top-up Order", short, "status"), "Failed")
		self.assertTrue(frappe.db.get_value("Top-up Order", short, "failure_reason"))
		self.assertEqual(frappe.db.get_value("Top-up Order", paid, "status"), "Credited")

	def test_a_recent_paid_top_up_is_credited_within_minutes(self):
		from central.billing.gateways.base import VerifiedPayment

		recent = self._order("pi_recent", hours_old=0.25)
		just_made = self._order("pi_just_made", hours_old=0.01)
		older = self._order("pi_older", hours_old=3)
		with gateway_status("succeeded") as adapter:
			adapter.find_order_payment.side_effect = lambda order_id: VerifiedPayment(
				order_id, True, 700, "INR", order_id=order_id
			)
			reconciliation.reconcile_recent_top_up_orders()

		self.assertEqual(frappe.db.get_value("Top-up Order", recent, "status"), "Credited")
		# The checkout callback still has a few minutes, and older orders wait for the hourly sweep.
		self.assertEqual(frappe.db.get_value("Top-up Order", just_made, "status"), "Created")
		self.assertEqual(frappe.db.get_value("Top-up Order", older, "status"), "Created")

	def test_a_gateway_outage_leaves_recent_top_ups_for_the_next_run_without_logging(self):
		from central.billing.gateways.base import GatewayTimeout

		order = self._order("pi_outage", hours_old=0.25)
		with gateway_status("succeeded") as adapter, patch("frappe.log_error") as log_error:
			adapter.find_order_payment.side_effect = GatewayTimeout("gateway down")
			reconciliation.reconcile_recent_top_up_orders()

		self.assertEqual(frappe.db.get_value("Top-up Order", order, "status"), "Created")
		log_error.assert_not_called()

	def test_an_unpaid_top_up_expires(self):
		order = self._order("pi_never", hours_old=8 * 24)
		with gateway_status("requires_payment_method") as adapter:
			adapter.find_order_payment.return_value = None
			reconciliation.reconcile_top_up_orders()
		self.assertEqual(frappe.db.get_value("Top-up Order", order, "status"), "Expired")
