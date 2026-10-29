# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The audit repair patch leaves each finding in a state the guards accept."""

from unittest.mock import patch

import frappe

from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team, ensure_trust_tier_level
from central.patches.v0_0 import repair_billing_audit_findings as repair

TEAM = "team-audit-repair"


class TestRepairBillingAuditFindings(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.delete("Tax Profile", {"team": TEAM})

	def test_staging_team_becomes_internal(self):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		with patch("central.billing.settings.provision_teams_as_trial", return_value=False):
			repair.mark_staging_teams_internal()
		self.assertTrue(frappe.db.get_value("Tax Profile", TEAM, "is_internal"))
		self.assertFalse(frappe.db.get_value("Team", TEAM, "is_staging_trial"))

	def test_staging_team_unpaid_invoice_is_waived(self):
		invoice = self._staging_team_invoice()
		with patch("central.billing.settings.provision_teams_as_trial", return_value=False):
			repair.mark_staging_teams_internal()
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Waived")

	def test_waive_gives_credit_back_to_a_wallet_with_unbooked_credit(self):
		credits.grant_promotional_credits(TEAM, 100, "INR")
		invoice = self._staging_team_invoice(credit_applied=40)
		frappe.db.set_value("Credit Wallet", credits.wallet_name(TEAM, "INR"), "balance", 2600)

		self._run_repair()

		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Waived")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2640)

	def test_wallet_short_of_its_ledger_leaves_the_invoice_to_an_operator(self):
		credits.grant_promotional_credits(TEAM, 100, "INR")
		invoice = self._staging_team_invoice(credit_applied=40)
		frappe.db.set_value("Credit Wallet", credits.wallet_name(TEAM, "INR"), "balance", 10)

		self._run_repair()

		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Open")
		self.assertTrue(frappe.db.get_value("Tax Profile", TEAM, "is_internal"))

	def _staging_team_invoice(self, credit_applied=0):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-09-01",
					"period_end": "2026-09-30",
					"currency": "INR",
					"subtotal": 100,
					"total": 100,
					"credit_applied": credit_applied,
					"expected_collection": 100 - credit_applied,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _run_repair(self):
		# The other steps rewrite rows across the site; this test is about the order of these two.
		with (
			patch("central.billing.settings.provision_teams_as_trial", return_value=False),
			patch.object(repair, "match_currency_to_country"),
			patch.object(repair, "pin_tiers_set_by_hand"),
		):
			repair.execute()

	def test_staging_team_is_kept_on_a_staging_site(self):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		self.addCleanup(frappe.db.set_value, "Team", TEAM, "is_staging_trial", 0)
		with patch("central.billing.settings.provision_teams_as_trial", return_value=True):
			repair.mark_staging_teams_internal()
		self.assertTrue(frappe.db.get_value("Team", TEAM, "is_staging_trial"))

	def test_india_team_never_invoiced_goes_back_to_inr(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		repair.match_currency_to_country()
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")

	def test_tier_set_by_hand_is_pinned_without_its_dead_cap(self):
		ensure_trust_tier_level("t-entry")
		frappe.db.set_value("Trust Tier Level", "t-entry", "is_default", 1)
		self.addCleanup(frappe.db.set_value, "Trust Tier Level", "t-entry", "is_default", 0)
		level = ensure_trust_tier_level("t-elite")
		frappe.db.set_value(
			"Billing Profile",
			TEAM,
			{"trust_tier_level": level, "manual_override": 0, "override_max_spend": 1000000},
		)
		repair.pin_tiers_set_by_hand()
		profile = frappe.db.get_value(
			"Billing Profile",
			TEAM,
			["manual_override", "override_max_spend", "promotion_basis"],
			as_dict=True,
		)
		self.assertEqual((profile.manual_override, profile.override_max_spend), (1, 0))
		self.assertTrue(profile.promotion_basis)

	def test_unexplained_wallet_balance_is_booked_and_moves_again(self):
		credits.grant_promotional_credits(TEAM, 100, "INR")
		frappe.db.set_value("Credit Wallet", credits.wallet_name(TEAM, "INR"), "balance", 2600)

		repair.book_wallet_balances_missing_from_the_ledger()

		credits.apply_credit(TEAM, 50, "INR", reference_type="Invoice", reference_name="INV-1")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2550)

	def test_team_holding_credit_in_its_currency_is_left_alone(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		credits.grant_promotional_credits(TEAM, 10, "USD")
		repair.match_currency_to_country()
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "USD")

	def test_team_with_a_method_in_another_currency_is_left_alone(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": "Stripe",
				"method_type": "Card",
				"status": "Active",
				"mandate_currency": "USD",
			}
		).insert(ignore_permissions=True)
		repair.match_currency_to_country()
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "USD")

	def test_team_whose_method_is_already_in_inr_is_moved_to_inr(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": "Stripe",
				"method_type": "Card",
				"status": "Pending Validation",
				"mandate_currency": "INR",
			}
		).insert(ignore_permissions=True)
		repair.match_currency_to_country()
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")
