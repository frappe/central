# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Profile validation: GSTIN format + India state ↔ GST state code."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import ensure_team

TEAM = "team-billing-profile"


def _profile(**overrides):
	values = {
		"doctype": "Billing Profile", "team": TEAM, "currency": "INR",
		"legal_name": f"{TEAM} Ltd", "address_line1": "1 Test Street", "city": "Pune",
		"state": "Maharashtra", "country": "India", "pincode": "411001",
	}
	values.update(overrides)
	if frappe.db.exists("Billing Profile", TEAM):
		doc = frappe.get_doc("Billing Profile", TEAM)
		doc.update(values)
	else:
		doc = frappe.get_doc(values)
	doc.save(ignore_permissions=True)
	return doc


class TestBillingProfile(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
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

	def test_non_india_skips_state_and_gstin_checks(self):
		# A free-text state and no GSTIN is fine outside India.
		doc = _profile(country="Germany", state="Hesse", gstin="")
		self.assertEqual(doc.state, "Hesse")

	def test_partial_profile_without_gstin_or_state_saves(self):
		# Profiles are often created incomplete (just team + currency); that must not throw.
		doc = _profile(state="", gstin="", legal_name="", address_line1="", city="", pincode="")
		self.assertEqual(doc.currency, "INR")
