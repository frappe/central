# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the ₹15,000 Action Required threshold (issue #50, ADR 0005)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.payments import collection_mode
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-collection"


def _set_mode(team, mode, reason=None):
	doc = frappe.get_doc("Billing Profile", team)
	doc.collection_mode = mode
	doc.collection_action_reason = reason
	doc.save(ignore_permissions=True)


class TestCollectionMode(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.delete("Trust Tier", {"team": TEAM})  # no tier → flat ₹15k threshold
		frappe.db.delete("Billing Notification Log", {"team": TEAM})

	def test_threshold_is_15k_without_a_tier(self):
		self.assertEqual(collection_mode.silent_threshold(TEAM), 15000.0)

	def test_threshold_is_capped_by_a_lower_tier(self):
		if not frappe.db.exists("Trust Tier Level", "t0"):
			frappe.get_doc({"doctype": "Trust Tier Level", "__newname": "t0", "tier": "t0",
							"sequence": 0, "is_default": 1, "max_spend": 8000,
							"max_resource_count": 5}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Trust Tier", "team": TEAM, "tier": "t0", "level": "t0",
						"max_spend": 8000, "max_resource_count": 5, "manual_override": 1}
					   ).insert(ignore_permissions=True)
		self.assertEqual(collection_mode.silent_threshold(TEAM), 8000.0)

	def test_emandate_under_threshold_stays_silent(self):
		_set_mode(TEAM, "emandate")
		st = collection_mode.evaluate(TEAM, projected_amount=9000)
		self.assertEqual(st["collection_mode"], "emandate")
		self.assertFalse(st["action_required"])

	def test_emandate_over_threshold_trips_action_required(self):
		_set_mode(TEAM, "emandate")
		st = collection_mode.evaluate(TEAM, projected_amount=18400)
		self.assertEqual(st["collection_mode"], "action_required")
		self.assertTrue(st["action_required"])
		self.assertEqual(st["reason"], "forecast_over_threshold")
		# A notification was raised for the customer to act on.
		self.assertTrue(frappe.db.exists(
			"Billing Notification Log", {"team": TEAM, "event_type": "Action Required"}))

	def test_trip_is_idempotent_one_notification(self):
		_set_mode(TEAM, "emandate")
		collection_mode.evaluate(TEAM, projected_amount=20000)
		collection_mode.evaluate(TEAM, projected_amount=25000)
		self.assertEqual(frappe.db.count(
			"Billing Notification Log", {"team": TEAM, "event_type": "Action Required"}), 1)

	def test_non_emandate_modes_are_never_tripped(self):
		# A prepaid team running a huge bill is not "action required" — it just draws
		# the wallet; only the silent e-mandate rail has the ₹15k ceiling.
		_set_mode(TEAM, "prepaid")
		st = collection_mode.evaluate(TEAM, projected_amount=99999)
		self.assertEqual(st["collection_mode"], "prepaid")
		self.assertFalse(st["action_required"])

	def test_customer_chooses_manual_checkout_clears_action(self):
		_set_mode(TEAM, "action_required", reason="forecast_over_threshold")
		st = collection_mode.choose(TEAM, "manual_checkout")
		self.assertEqual(st["collection_mode"], "manual_checkout")
		self.assertFalse(st["action_required"])
		self.assertIsNone(frappe.db.get_value("Billing Profile", TEAM, "collection_action_reason"))

	def test_customer_chooses_prepaid_clears_action(self):
		_set_mode(TEAM, "action_required", reason="forecast_over_threshold")
		st = collection_mode.choose(TEAM, "prepaid")
		self.assertEqual(st["collection_mode"], "prepaid")
		self.assertFalse(st["action_required"])

	def test_invalid_mode_choice_is_rejected(self):
		_set_mode(TEAM, "action_required")
		# A customer cannot silently put themselves (back) on a silent auto rail.
		with self.assertRaises(frappe.ValidationError):
			collection_mode.choose(TEAM, "emandate")
		with self.assertRaises(frappe.ValidationError):
			collection_mode.choose(TEAM, "stripe_auto")


class TestAdapterSilentCharge(IntegrationTestCase):
	"""The capability flags that drive which rail may auto-charge (ADR 0005)."""

	def test_stripe_charges_any_amount_silently(self):
		from central.billing.gateways.stripe_adapter import StripeAdapter

		a = StripeAdapter(frappe._dict())
		self.assertTrue(a.supports_off_session_charge)
		self.assertTrue(a.can_charge_silently(10_00_00_000))  # ₹10,00,000 — fine

	def test_razorpay_silent_only_up_to_15k(self):
		from central.billing.gateways.razorpay_adapter import RazorpayAdapter

		a = RazorpayAdapter(frappe._dict())
		self.assertTrue(a.can_charge_silently(15_00_000))      # exactly ₹15,000
		self.assertFalse(a.can_charge_silently(15_00_001))     # one paisa over
		self.assertTrue(a.requires_predebit_notice)
