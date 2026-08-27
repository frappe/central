# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Settlement fallback: primary -> backup payment methods (issue #28)."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.gateways.base import PaymentResult
from central.billing.payments import charges, collection, payments
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team, make_plan

TEAM = "team-fallback"
PLAN = "bundle-fallback-test"
GATEWAY = "Stripe"


def _result(success, txn_id):
	return PaymentResult(
		success=success,
		status="Captured" if success else "Failed",
		gateway_transaction_id=txn_id if success else None,
		failure_code=None if success else "card_declined",
		failure_reason=None if success else "declined",
	)


@contextmanager
def stub_charges(results):
	"""Patch the adapter so each successive charge() returns the next scripted
	(success, txn_id) result."""
	adapter = MagicMock()
	adapter.charge.side_effect = [_result(s, t) for s, t in results]
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class FallbackTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		make_stripe_gateway()
		self._purge()
		self.primary = self._card("Visa ····0001", "pm_primary", priority=0)
		self.backup = self._card("Visa ····0002", "pm_backup", priority=1)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Payment Attempt", "Invoice"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Group", {"team": TEAM})
		for we in frappe.get_all("Webhook Event", pluck="name"):
			frappe.db.delete("Webhook Event", {"name": we})
		frappe.db.commit()

	def _card(self, label, gw_id, priority, reauth=0, billing_group=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"billing_group": billing_group,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Active",
					"display_label": label,
					"gateway_method_id": gw_id,
					"gateway_customer_id": "cus_1",
					"priority": priority,
					"is_default": 1 if priority == 0 else 0,
					"reauth_required": reauth,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _open_invoice(self, total=1000, billing_group=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"billing_group": billing_group,
					"status": "Open",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"credit_applied": 0,
					"expected_collection": total,
					"amount_paid": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _failure_event(self, txn_id):
		payload = {
			"id": f"evt_{txn_id}",
			"type": "payment_intent.payment_failed",
			"data": {"object": {"id": txn_id}},
		}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": GATEWAY,
					"gateway_event_id": f"evt_{txn_id}",
					"event_type": "payment_intent.payment_failed",
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _attempts(self):
		return frappe.get_all(
			"Payment Attempt",
			filters={"team": TEAM},
			fields=["name", "payment_method", "status", "gateway_transaction_id"],
			order_by="creation asc",
		)


class TestSyncFallback(FallbackTestBase):
	def test_sync_decline_rotates_to_backup_in_same_run(self):
		inv = self._open_invoice()
		with stub_charges([(False, None), (True, "pi_backup")]) as adapter:
			collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 2)  # primary then backup
		attempts = self._attempts()
		self.assertEqual([a.payment_method for a in attempts], [self.primary, self.backup])
		self.assertEqual(attempts[0].status, "Failed")
		self.assertEqual(attempts[1].status, "Captured")  # awaiting webhook, but charged

	def test_all_methods_fail_leaves_invoice_open_without_repeat(self):
		inv = self._open_invoice()
		with stub_charges([(False, None), (False, None)]) as adapter:
			result = collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 2)  # each method tried exactly once
		self.assertEqual(result["reason"], "no_method")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")
		# Re-running does not re-charge an already-failed method (escalate, don't repeat).
		with stub_charges([]) as adapter:
			collection.collect_invoice(inv)
		self.assertEqual(adapter.charge.call_count, 0)

	def test_reauth_required_method_is_skipped(self):
		frappe.db.set_value("Payment Method", self.backup, "reauth_required", 1)
		inv = self._open_invoice()
		with stub_charges([(False, None)]) as adapter:
			result = collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 1)  # only the primary; backup skipped
		self.assertEqual(result["reason"], "no_method")


class TestWebhookFallback(FallbackTestBase):
	def test_async_decline_rotates_to_backup(self):
		inv = self._open_invoice()
		with stub_charges([(True, "pi_primary"), (True, "pi_backup")]):
			collection.collect_invoice(inv)  # primary captured, awaiting webhook
			event = self._failure_event("pi_primary")  # bank reverses the primary
			charges.apply_webhook(event)  # -> rotates to backup

		attempts = {a.gateway_transaction_id: a for a in self._attempts() if a.gateway_transaction_id}
		self.assertIn("pi_backup", attempts)
		self.assertEqual(attempts["pi_backup"].payment_method, self.backup)
		primary_attempt = next(a for a in self._attempts() if a.payment_method == self.primary)
		self.assertEqual(primary_attempt.status, "Failed")


class TestMethodOrdering(FallbackTestBase):
	def test_duplicate_card_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._card("Visa ····0001 again", "pm_primary", priority=2)

	def test_make_primary_reorders_and_mirrors_is_default(self):
		payments.set_default_payment_method(self.backup)
		self.assertEqual(frappe.db.get_value("Payment Method", self.backup, "priority"), 0)
		self.assertEqual(frappe.db.get_value("Payment Method", self.backup, "is_default"), 1)
		self.assertEqual(frappe.db.get_value("Payment Method", self.primary, "priority"), 1)
		self.assertEqual(frappe.db.get_value("Payment Method", self.primary, "is_default"), 0)

	def test_reorder_densifies(self):
		payments.reorder_payment_methods(TEAM, json.dumps([self.backup, self.primary]))
		self.assertEqual(frappe.db.get_value("Payment Method", self.backup, "priority"), 0)
		self.assertEqual(frappe.db.get_value("Payment Method", self.primary, "priority"), 1)

	def test_delete_redensifies(self):
		payments.delete_payment_method(self.primary)
		self.assertEqual(frappe.db.get_value("Payment Method", self.backup, "priority"), 0)
		self.assertEqual(frappe.db.get_value("Payment Method", self.backup, "is_default"), 1)


class TestBillingGroupCardRouting(FallbackTestBase):
	"""A group invoice charges its own earmarked card(s) first, falling back to the
	team's general cards (self.primary / self.backup from setUp) if exhausted or
	none are set. The consolidated invoice never uses a group's earmarked card."""

	def _group(self, title="Customer X"):
		return frappe.get_doc({"doctype": "Billing Group", "title": title, "team": TEAM}).insert().name

	def test_group_invoice_charges_its_own_card_first(self):
		group = self._group()
		self._card("Group card", "pm_group", priority=2, billing_group=group)
		inv = self._open_invoice(billing_group=group)

		with stub_charges([(True, "pi_group")]) as adapter:
			collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 1)
		attempt = self._attempts()[0]
		self.assertEqual(
			frappe.db.get_value("Payment Method", attempt.payment_method, "gateway_method_id"), "pm_group"
		)

	def test_group_invoice_falls_back_to_general_cards_when_its_own_declines(self):
		group = self._group()
		self._card("Group card", "pm_group", priority=2, billing_group=group)
		inv = self._open_invoice(billing_group=group)

		# Group's own card declines, then falls through to the general primary.
		with stub_charges([(False, None), (True, "pi_primary")]) as adapter:
			collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 2)
		methods_tried = [a.payment_method for a in self._attempts()]
		self.assertEqual(
			[frappe.db.get_value("Payment Method", m, "gateway_method_id") for m in methods_tried],
			["pm_group", "pm_primary"],
		)

	def test_group_invoice_with_no_own_card_uses_the_general_pool_directly(self):
		group = self._group()  # no card earmarked to it
		inv = self._open_invoice(billing_group=group)

		with stub_charges([(True, "pi_primary")]) as adapter:
			collection.collect_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 1)
		attempt = self._attempts()[0]
		self.assertEqual(
			frappe.db.get_value("Payment Method", attempt.payment_method, "gateway_method_id"), "pm_primary"
		)

	def test_consolidated_invoice_never_uses_a_groups_earmarked_card(self):
		group = self._group()
		self._card("Group card", "pm_group", priority=-1, billing_group=group)  # would sort first if unscoped
		inv = self._open_invoice(billing_group=None)

		with stub_charges([(True, "pi_primary")]) as adapter:
			collection.collect_invoice(inv)

		attempt = self._attempts()[0]
		self.assertEqual(
			frappe.db.get_value("Payment Method", attempt.payment_method, "gateway_method_id"), "pm_primary"
		)

	def test_two_groups_never_use_each_others_earmarked_card(self):
		x = self._group("Customer X")
		y = self._group("Customer Y")
		self._card("X card", "pm_x", priority=2, billing_group=x)
		inv_y = self._open_invoice(billing_group=y)

		# Y's invoice must skip X's card entirely and land on the general primary.
		with stub_charges([(True, "pi_primary")]) as adapter:
			collection.collect_invoice(inv_y)

		attempt = self._attempts()[0]
		self.assertEqual(
			frappe.db.get_value("Payment Method", attempt.payment_method, "gateway_method_id"), "pm_primary"
		)

	def test_manual_pay_now_follows_the_same_routing_rule(self):
		# charges._resolve_method (the manual "pay now" path) unified onto the same
		# rule as collection.collect_invoice — same group-first, general-fallback.
		group = self._group()
		self._card("Group card", "pm_group", priority=2, billing_group=group)
		inv = self._open_invoice(billing_group=group)

		with stub_charges([(True, "pi_group")]) as adapter:
			charges.pay_invoice(inv)

		self.assertEqual(adapter.charge.call_count, 1)
		attempt = self._attempts()[0]
		self.assertEqual(
			frappe.db.get_value("Payment Method", attempt.payment_method, "gateway_method_id"), "pm_group"
		)
