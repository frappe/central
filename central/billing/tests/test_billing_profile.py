# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Profile validation: GSTIN format + India state ↔ GST state code."""

import frappe

from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
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


def _invoice(team=TEAM, currency="INR"):
	"""Minimal issued invoice so the team counts as "already invoiced"."""
	return frappe.get_doc(
		{"doctype": "Invoice", "team": team, "invoice_type": "Billable", "status": "Open",
		 "period_start": "2099-01-01", "period_end": "2099-01-31", "currency": currency,
		 "subtotal": 100, "total": 100, "amount_paid": 0}
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

	def test_non_india_skips_state_and_gstin_checks(self):
		# A free-text state and no GSTIN is fine outside India.
		doc = _profile(country="Germany", state="Hesse", gstin="")
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
		_profile(country="India", currency="INR")
		_invoice()
		with self.assertRaises(frappe.ValidationError):
			_profile(currency="USD")

	def test_country_locked_once_team_is_invoiced(self):
		_profile(country="India", currency="INR")
		_invoice()
		with self.assertRaises(frappe.ValidationError):
			_profile(country="Germany", state="Hesse", gstin="")

	def test_other_fields_still_editable_after_invoicing(self):
		# Legal name / address / GSTIN can change post-invoice — only the two
		# invoice-defining fields lock.
		_profile(country="India", currency="INR")
		_invoice()
		doc = _profile(legal_name="Renamed Ltd", address_line1="9 New Road", gstin="27AAPFU0939F1ZV")
		self.assertEqual(doc.legal_name, "Renamed Ltd")
