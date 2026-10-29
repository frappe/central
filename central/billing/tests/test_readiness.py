# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.platform import alerts, invariants, readiness
from central.billing.report.billing_invariant_violations import billing_invariant_violations as report
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	billing_settings,
	clear_team_tier,
	complete_billing_profile,
	ensure_trust_tier_level,
	make_billing_subscription,
	make_plan,
	set_team_tier,
)

TEAM = "team-readiness"
CLUSTER = "ap-south-1"
PLAN = "bundle-readiness"


def _found(check: str, team: str = TEAM) -> list:
	return [v for v in invariants.audit(only=check, checks=readiness.CHECKS) if v.team == team]


def _found_run(check: str) -> list:
	return [
		v for v in invariants.audit(only=check, checks=readiness.CHECKS) if v.subject_doctype == "Billing Run"
	]


def _accounting_sync(on: bool):
	return patch("central.billing.ingester.connection.enabled", return_value=on)


class TestReadiness(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self.subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.subscription, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.set_value("Subscription", self.subscription, "enabled", 1)
		complete_billing_profile(TEAM)
		set_team_tier(TEAM, max_spend=5000)
		self.addCleanup(clear_team_tier, TEAM)

	def test_india_billed_in_usd_is_found(self):
		frappe.db.set_value("Billing Profile", TEAM, "currency", "USD")
		self.assertEqual(len(_found("B1")), 1)

	def test_spend_over_the_tier_cap_is_found(self):
		set_team_tier(TEAM, max_spend=500)
		[violation] = _found("T1")
		self.assertEqual((violation.expected, violation.actual), (500, 1000))

	def test_internal_team_is_not_held_to_its_tier(self):
		set_team_tier(TEAM, max_spend=500)
		frappe.get_doc(
			{"doctype": "Tax Profile", "team": TEAM, "is_internal": 1, "internal_reason": "Our own team"}
		).insert(ignore_permissions=True)
		self.assertEqual(_found("T1"), [])

	def test_unpriced_subscription_is_found(self):
		add_segment(self.subscription, "Plan Changed", 0, "2026-06-02 00:00:00")
		self.assertEqual(len(_found("S1")), 1)

	def test_team_with_no_way_to_pay_is_found(self):
		[violation] = _found("W1")
		self.assertEqual((violation.expected, violation.actual), (1000, 0))

	def test_team_on_manual_checkout_can_pay(self):
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Manual Checkout")
		self.assertEqual(_found("W1"), [])

	def test_payment_method_in_another_currency_is_found(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": make_stripe_gateway().name,
				"method_type": "Card",
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		method.db_set("mandate_currency", "INR")
		self.assertEqual(_found("B2"), [])

		method.db_set("mandate_currency", "USD")
		self.assertEqual(len(_found("B2")), 1)

	def test_team_with_missing_billing_details_is_found(self):
		with _accounting_sync(False):
			self.assertEqual(_found("B3"), [])
			frappe.db.set_value("Billing Profile", TEAM, "legal_name", None)
			[violation] = _found("B3")
		self.assertIn("legal_name", violation.detail)

	def test_team_not_in_the_accounting_system_is_found(self):
		frappe.db.set_value("Billing Profile", TEAM, "profile_id", None)
		with _accounting_sync(True):
			self.assertEqual(len(_found("B3")), 1)

	def test_incomplete_accounting_setup_is_found(self):
		with _accounting_sync(False):
			self.assertEqual(_found("B4", team=None), [])
		with billing_settings(company=None), _accounting_sync(True):
			[violation] = _found("B4", team=None)
		self.assertIn("company", violation.detail)

	def test_servers_over_the_tier_limit_are_found(self):
		self.assertEqual(_found("T2"), [])
		limit = frappe.db.get_value("Trust Tier Level", "t1", "max_resource_count")
		# The test sweep commits, so put the shared level back by hand.
		self.addCleanup(frappe.db.set_value, "Trust Tier Level", "t1", "max_resource_count", limit)
		frappe.db.set_value("Trust Tier Level", "t1", "max_resource_count", 0)
		[violation] = _found("T2")
		self.assertEqual((violation.expected, violation.actual), (0, 1))

	def test_tier_with_no_recorded_reason_is_found(self):
		set_team_tier(TEAM, level=ensure_trust_tier_level("t-readiness"))
		self.assertEqual(len(_found("T3")), 1)

		frappe.db.set_value("Billing Profile", TEAM, "promotion_basis", "Pinned for a pilot")
		self.assertEqual(_found("T3"), [])

	def test_running_server_with_no_subscription_is_found(self):
		server = frappe.db.get_value("Subscription", self.subscription, "server_id")
		frappe.db.set_value("Virtual Machine", server, "status", "Running")
		self.assertEqual(_found("S2"), [])

		frappe.db.set_value("Subscription", self.subscription, "enabled", 0)
		self.assertEqual(len(_found("S2")), 1)

	def test_terminated_server_still_billed_is_found(self):
		server = frappe.db.get_value("Subscription", self.subscription, "server_id")
		frappe.db.set_value("Virtual Machine", server, "status", "Terminated")
		self.assertEqual(len(_found("S3")), 1)

		frappe.db.set_value("Subscription", self.subscription, "enabled", 0)
		self.assertEqual(_found("S3"), [])

	def test_promotional_credit_with_no_expiry_is_found(self):
		entry = frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": TEAM,
				"entry_type": "Credit",
				"amount": 100,
				"currency": "INR",
				"reference_type": "Promotion",
			}
		).insert(ignore_permissions=True)
		entry.db_set("expires_on", "2026-12-31")
		with patch.object(readiness.settings, "promotional_credit_validity_days", return_value=30):
			self.assertEqual(_found("W2"), [])
			entry.db_set("expires_on", None)
			self.assertEqual(len(_found("W2")), 1)

	def test_staging_trial_outside_staging_is_found(self):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		self.addCleanup(frappe.db.set_value, "Team", TEAM, "is_staging_trial", 0)
		with patch.object(readiness.settings, "provision_teams_as_trial", return_value=False):
			self.assertEqual(len(_found("X1")), 1)

	def test_a_month_with_billing_but_no_run_is_found(self):
		from central.billing.revenue.invoicing.run import billing_period

		frappe.db.delete("Billing Run", {"period_end": billing_period()[1]})
		frappe.db.set_value("Subscription", self.subscription, "start_date", "2020-01-01")

		found = _found_run("B5")
		self.assertEqual(len(found), 1)
		self.assertIn("has not started", found[0].detail)

	def test_a_run_that_drafted_nothing_for_hours_is_found(self):
		from central.billing.revenue.invoicing.run import billing_period

		period_end = billing_period()[1]
		frappe.db.delete("Billing Run", {"period_end": period_end})
		frappe.get_doc(
			{
				"doctype": "Billing Run",
				"period_start": period_end,
				"period_end": period_end,
				"status": "Drafting",
				"teams": 5,
				"started_at": frappe.utils.add_to_date(None, hours=-4),
			}
		).insert(ignore_permissions=True)

		self.assertIn("drafted no invoice", _found_run("B5")[0].detail)

	def test_a_draft_left_waiting_for_hours_is_found_but_a_held_one_is_not(self):
		from central.billing.revenue.invoicing.run import billing_period

		_, period_end = billing_period()
		frappe.get_doc(
			{
				"doctype": "Billing Run",
				"period_start": period_end,
				"period_end": period_end,
				"status": "Collecting",
			}
		).insert(ignore_permissions=True)
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"period_start": period_end,
				"period_end": period_end,
				"currency": "INR",
				"status": "Draft",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Invoice", invoice.name, "creation", frappe.utils.add_to_date(None, hours=-5))

		self.assertEqual(_found_run("B5")[0].actual, 1)
		frappe.db.set_value("Invoice", invoice.name, "hold_reason", "Billing Details")
		self.assertEqual(_found_run("B5"), [])

	def test_summary_has_a_row_per_check(self):
		_, rows, _, _ = report.execute({"view": "Summary", "team": TEAM})
		checks = {row["check"]: row for row in rows}
		self.assertEqual(set(checks), set(invariants.CHECKS) | set(readiness.CHECKS))
		self.assertEqual(checks["W1"]["violations"], 1)

	def test_summary_lists_only_the_checks_that_ran(self):
		_, rows, _, _ = report.execute({"view": "Summary", "kind": "Readiness", "team": TEAM})
		self.assertEqual({row["check"] for row in rows}, set(readiness.CHECKS))

		_, rows, _, _ = report.execute({"view": "Summary", "check": "W1"})
		self.assertEqual([row["check"] for row in rows], ["W1"])

	def test_readiness_gaps_reach_the_operator_alerts(self):
		gaps = [a for a in alerts.readiness_gaps() if a["team"] == TEAM]
		self.assertIn("readiness", {a["alert"] for a in gaps})
