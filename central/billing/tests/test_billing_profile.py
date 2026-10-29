# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Profile validation: GSTIN format + India state ↔ GST state code."""

import frappe

from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team, ensure_trust_tier_level

TEAM = "team-billing-profile"


def _profile(**overrides):
	values = {
		"doctype": "Billing Profile",
		"team": TEAM,
		"currency": "INR",
		"legal_name": f"{TEAM} Ltd",
		"address_line1": "1 Test Street",
		"city": "Pune",
		"state": "Maharashtra",
		"country": "India",
		"pincode": "411001",
	}
	values.update(overrides)
	if frappe.db.exists("Billing Profile", TEAM):
		doc = frappe.get_doc("Billing Profile", TEAM)
		doc.update(values)
	else:
		doc = frappe.get_doc(values)
	doc.save(ignore_permissions=True)
	return doc


def _invoice(team=TEAM, currency="INR"):
	"""Minimal issued invoice so the team counts as "already invoiced"."""
	return frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": team,
			"invoice_type": "Billable",
			"status": "Open",
			"period_start": "2099-01-01",
			"period_end": "2099-01-31",
			"currency": currency,
			"subtotal": 100,
			"total": 100,
			"amount_paid": 0,
		}
	).insert(ignore_permissions=True)


class TestBillingProfile(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})

	def test_valid_gstin_matching_state_saves(self):
		doc = _profile(state="Maharashtra", gstin="27AAPFU0939F1ZV")
		self.assertEqual(doc.gstin, "27AAPFU0939F1ZV")

	def test_gstin_is_uppercased(self):
		doc = _profile(state="Maharashtra", gstin="27aapfu0939f1zv")
		self.assertEqual(doc.gstin, "27AAPFU0939F1ZV")

	def test_malformed_gstin_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(gstin="NOTAGSTIN")

	def test_gstin_state_code_must_match_selected_state(self):
		# 27 is Maharashtra; claiming Karnataka (29) must fail.
		with self.assertRaises(frappe.ValidationError):
			_profile(state="Karnataka", gstin="27AAPFU0939F1ZV")

	def test_gstin_requires_a_state(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(state="", gstin="27AAPFU0939F1ZV")

	def test_unrecognised_india_state_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(state="Atlantis")

	def test_an_indian_mobile_is_kept_without_its_spacing(self):
		self.assertEqual(_profile(phone="+91 91234-56780").phone, "+919123456780")

	def test_an_indian_number_that_is_not_a_mobile_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(phone="1234567")

	def test_a_phone_abroad_needs_8_to_15_digits(self):
		self.assertEqual(
			_profile(country="Germany", currency="USD", phone="+49 30 1234567").phone, "+49301234567"
		)
		with self.assertRaises(frappe.ValidationError):
			_profile(country="Germany", currency="USD", phone="12ab")

	def test_non_india_skips_state_and_gstin_checks(self):
		# A free-text state and no GSTIN is fine outside India.
		doc = _profile(country="Germany", currency="USD", state="Hesse", gstin="")
		self.assertEqual(doc.state, "Hesse")

	def test_partial_profile_without_gstin_or_state_saves(self):
		# Profiles are often created incomplete (just team + currency); that must not throw.
		doc = _profile(state="", gstin="", legal_name="", address_line1="", city="", pincode="")
		self.assertEqual(doc.currency, "INR")

	def test_country_and_currency_editable_before_any_invoice(self):
		_profile(country="India", currency="INR")
		doc = _profile(country="Germany", currency="USD", state="Hesse", gstin="")
		self.assertEqual(doc.country, "Germany")
		self.assertEqual(doc.currency, "USD")

	def test_currency_locked_once_team_is_invoiced(self):
		_profile(country="Germany", currency="USD", state="Hesse", gstin="")
		_invoice(currency="USD")
		with self.assertRaises(frappe.ValidationError):
			_profile(currency="EUR")

	def test_country_locked_once_team_is_invoiced(self):
		_profile(country="Germany", currency="USD", state="Hesse", gstin="")
		_invoice(currency="USD")
		with self.assertRaises(frappe.ValidationError):
			_profile(country="France", state="Paris")

	def test_india_is_billed_only_in_inr(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(country="India", currency="USD")

	def test_only_india_is_billed_in_inr(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(country="Germany", currency="INR", state="Hesse", gstin="")

	def test_currency_change_refused_while_a_mandate_holds_the_old_one(self):
		_profile(country="India", currency="INR")
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": "Stripe",
				"method_type": "Card",
				"status": "Pending Validation",
				"mandate_currency": "INR",
				"mandate_max_amount": 15000,
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			_profile(country="Germany", currency="USD", state="Hesse", gstin="")

	def test_other_fields_still_editable_after_invoicing(self):
		# Legal name / address / GSTIN can change post-invoice — only the two
		# invoice-defining fields lock.
		_profile(country="India", currency="INR")
		_invoice()
		doc = _profile(legal_name="Renamed Ltd", address_line1="9 New Road", gstin="27AAPFU0939F1ZV")
		self.assertEqual(doc.legal_name, "Renamed Ltd")


class TestTierSetByHand(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		frappe.db.delete("Billing Profile", {"team": TEAM})
		frappe.db.delete("Billing Event", {"team": TEAM})
		self.entry = ensure_trust_tier_level("t1")
		self.higher = ensure_trust_tier_level("t2")
		_profile(trust_tier_level=self.entry)

	def test_tier_change_needs_a_reason(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(trust_tier_level=self.higher)

	def test_tier_change_by_hand_is_pinned_and_logged(self):
		doc = _profile(trust_tier_level=self.higher, promotion_basis="Strategic account")

		self.assertTrue(doc.manual_override)
		self.assertEqual(doc.trust_tier, "t2")
		self.assertIsNotNone(doc.promoted_at)
		event = frappe.get_all(
			"Billing Event",
			filters={"team": TEAM, "event_type": "Trust Tier Changed"},
			fields=["from_state", "to_state", "reason"],
		)
		self.assertEqual(event[0].to_state, self.higher)
		self.assertEqual(event[0].reason, "Strategic account")

	def test_unpinning_drops_the_bespoke_cap(self):
		_profile(override_max_spend=50000, promotion_basis="Approved by finance")
		doc = _profile(manual_override=0)

		self.assertEqual(doc.override_max_spend, 0)

	def test_system_tier_change_is_not_pinned(self):
		doc = frappe.get_doc("Billing Profile", TEAM)
		doc.trust_tier_level = self.higher
		doc.flags.tier_set_by_system = True
		doc.save(ignore_permissions=True)

		self.assertFalse(doc.manual_override)
		self.assertEqual(doc.trust_tier, "t2")
