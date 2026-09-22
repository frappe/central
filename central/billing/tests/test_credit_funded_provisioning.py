# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing details are asked for when credits stop covering the bill, not before.

Provisioning is allowed while the wallet funds it; the invoice is held until the
details arrive.
"""

from unittest.mock import MagicMock, patch

import frappe

from central.api import servers
from central.billing import settings
from central.billing.api.dashboard import account
from central.billing.payments import settlement
from central.billing.platform import alerts as billing_alerts
from central.billing.revenue import credits, invoicing
from central.billing.revenue.invoicing import run
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	run_enqueued_inline,
	set_team_tier,
)

TEAM = "team-credit-funded"
REGION = "ap-south-1"
PLAN = "bundle-credit-funded"
RATE = 1500.0


class CreditFundedTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(REGION)
		self.plan = make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": RATE}])
		self._purge()
		# A signup-shaped profile: the country and the currency it implies, and
		# nothing else — exactly what provision_signup_billing stamps from the IP.
		set_team_tier(TEAM, level="t0", max_spend=100000)
		frappe.set_user("Administrator")

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in (
			"Invoice",
			"Credit Ledger Entry",
			"Billing Profile",
			"Billing Notification Log",
			"Team Notification",
		):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		for asset in frappe.get_all("Asset", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Asset", {"name": asset})

	def _grant(self, amount):
		credits.grant_promotional_credits(TEAM, amount, "INR")

	def _draft(self, total=1000, invoice_type="Billable", period_end="2026-06-30"):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": invoice_type,
					"status": "Draft",
					"period_start": "2026-06-01",
					"period_end": period_end,
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"expected_collection": total,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _create_server(self, vm_id="vm-credit-funded"):
		"""Call the endpoint with Atlas stubbed, returning the created VM id."""
		client = MagicMock()
		client.create_vm.return_value = {
			"name": vm_id,
			"team": TEAM,
			"title": "web-1",
			"status": "Running",
			"vcpus": 2,
			"memory_megabytes": 4096,
			"disk_gigabytes": 40,
		}
		with patch.object(servers.AtlasClient, "for_region", return_value=client):
			return servers.create_server(
				team=TEAM,
				region=REGION,
				title="web-1",
				plan=self.plan,
				vcpus=2,
				memory_megabytes=4096,
				disk_gigabytes=40,
			)


class TestCreditFundedProvisioning(CreditFundedTestBase):
	def test_credits_create_a_server_without_billing_details(self):
		self._grant(5000)

		out = self._create_server()

		self.assertTrue(out["subscription"])
		# Still no legal name or address on file — and nothing asked for one.
		self.assertFalse(frappe.db.get_value("Billing Profile", TEAM, "legal_name"))

	def test_details_are_asked_for_once_credits_fall_short(self):
		self._grant(500)  # a third of the plan's monthly rate

		with self.assertRaises(frappe.ValidationError) as caught:
			self._create_server()

		self.assertIn("legal name", str(caught.exception))

	def test_no_credits_asks_for_details_as_before(self):
		with self.assertRaises(frappe.ValidationError):
			self._create_server()

	def test_headroom_shrinks_as_credits_fund_running_resources(self):
		self._grant(2000)  # covers one server at 1500, not two

		self._create_server(vm_id="vm-credit-funded-1")
		with self.assertRaises(frappe.ValidationError):
			self._create_server(vm_id="vm-credit-funded-2")

	def test_a_complete_profile_needs_no_credits(self):
		complete_billing_profile(TEAM)

		self.assertTrue(self._create_server()["subscription"])

	def test_an_unpriceable_plan_is_never_treated_as_funded(self):
		# A plan with no rate in the team's currency cannot be shown to fit the
		# wallet, so the request falls through to the full requirement.
		self._grant(50000)
		unpriced = make_plan(
			"bundle-credit-funded-usd", rates=[{"cluster": "", "currency": "USD", "rate": 20}]
		)

		self.assertFalse(settlement.wallet_funds(TEAM, servers._plan_rate(TEAM, unpriced, REGION)))


class TestCreditFundedHeadroom(CreditFundedTestBase):
	def test_headroom_is_the_wallet_under_the_tier_cap(self):
		self._grant(3000)

		self.assertEqual(settlement.credit_funded_headroom(TEAM), 3000)

	def test_the_tier_cap_still_bounds_a_large_wallet(self):
		set_team_tier(TEAM, level="t0", max_spend=1000)
		self._grant(9000)

		self.assertEqual(settlement.credit_funded_headroom(TEAM), 1000)

	def test_no_credits_is_no_headroom_even_under_a_tier(self):
		# Deliberately NOT effective_spend_cap's behaviour: that falls back to the
		# tier cap, which is only safe as a ceiling when a card backs it.
		self.assertEqual(settlement.credit_funded_headroom(TEAM), 0)

	def test_money_movement_stays_strict_however_rich_the_wallet(self):
		from central.billing.api.dashboard._shared import _require_billing_setup

		self._grant(50000)

		with self.assertRaises(frappe.ValidationError):
			_require_billing_setup(TEAM)


class TestInvoiceHeldForBillingDetails(CreditFundedTestBase):
	"""An invoice is held at Draft until we have a legal name to make it out to."""

	def test_a_billable_invoice_is_held_and_the_customer_asked(self):
		self._grant(5000)
		invoice = self._draft()

		result = invoicing.open_and_collect(invoice)

		self.assertEqual(result["held"], "billing_details")
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Draft")
		# Credits are untouched: nothing was settled against an invoice never issued.
		self.assertEqual(credits.get_balance(TEAM)["balance"], 5000)
		self.assertTrue(
			frappe.db.exists(
				"Billing Notification Log",
				{"team": TEAM, "event_type": "Billing Details Required", "reference_name": invoice},
			)
		)

	def test_the_held_draft_settles_once_the_details_arrive(self):
		self._grant(5000)
		invoice = self._draft()
		invoicing.open_and_collect(invoice)

		complete_billing_profile(TEAM)
		result = invoicing.open_and_collect(invoice)

		self.assertEqual(result["status"], "Paid")  # covered by the credits in full
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Paid")

	def test_a_held_draft_is_not_counted_as_settled(self):
		self._grant(5000)
		invoice = self._draft()

		counters = run.settle_draft_page("2026-07-01", "", "zzzz")

		self.assertEqual(counters["held"], 1)
		self.assertEqual(counters["settled"], 0)
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Draft")

	def test_completing_the_profile_settles_what_was_held(self):
		# Otherwise the customer waits for the next monthly run to be billed for
		# credits they have already been provisioned against.
		self._grant(5000)
		invoice = self._draft()
		invoicing.open_and_collect(invoice)

		with patch.object(frappe, "enqueue", run_enqueued_inline):
			complete_billing_profile(TEAM)
			account._release_held_invoices(TEAM)

		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Paid")

	def test_a_complete_profile_with_nothing_held_enqueues_nothing(self):
		complete_billing_profile(TEAM)

		with patch.object(frappe, "enqueue") as enqueue:
			account._release_held_invoices(TEAM)

		enqueue.assert_not_called()

	def test_a_cost_report_is_never_held(self):
		# A cost report is a record of what we subsidised, not a bill — there is
		# nobody to make it out to.
		invoice = self._draft(invoice_type="Cost Report")

		result = invoicing.open_and_collect(invoice)

		self.assertTrue(result["cost_report"])
		self.assertEqual(frappe.db.get_value("Invoice", invoice, "status"), "Open")


class TestBillingDetailsEscalation(CreditFundedTestBase):
	"""A bill that waits too long stops being funded and starts paging the operators."""

	def _overdue_draft(self):
		grace = settings.billing_details_grace_days()
		return self._draft(period_end=frappe.utils.add_days(frappe.utils.nowdate(), -grace - 1))

	def test_credit_stops_funding_once_a_bill_has_waited_too_long(self):
		self._grant(5000)
		self.assertEqual(settlement.credit_funded_headroom(TEAM), 5000)

		self._overdue_draft()

		self.assertEqual(settlement.credit_funded_headroom(TEAM), 0)
		with self.assertRaises(frappe.ValidationError):
			self._create_server()

	def test_a_bill_still_inside_the_grace_period_funds_as_before(self):
		self._grant(5000)
		self._draft(period_end=frappe.utils.nowdate())

		self.assertEqual(settlement.credit_funded_headroom(TEAM), 5000)

	def test_a_long_held_invoice_pages_the_operators(self):
		invoice = self._overdue_draft()

		alerts = [a for a in billing_alerts.held_invoices() if a["team"] == TEAM]

		self.assertEqual(len(alerts), 1)
		self.assertEqual(alerts[0]["subject"], invoice)

	def test_a_recent_hold_does_not_page_anybody(self):
		self._draft(period_end=frappe.utils.nowdate())

		self.assertFalse([a for a in billing_alerts.held_invoices() if a["team"] == TEAM])


class TestBillingDetailsReminder(CreditFundedTestBase):
	def test_a_billable_team_without_details_is_asked_daily(self):
		self._grant(5000)
		self._create_server()

		asked = settlement.run_billing_details_reminder()

		self.assertGreaterEqual(asked, 1)
		self.assertTrue(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Billing Details Required"}
			)
		)

	def test_a_team_running_nothing_is_left_alone(self):
		# Its subscriptions are all disabled: no bill is coming, so there is nothing
		# to ask for. Asking anyway is a daily nag about an invoice that never arrives.
		self._grant(5000)
		self._create_server()
		frappe.db.set_value("Subscription", {"team": TEAM}, "enabled", 0)

		settlement.run_billing_details_reminder()

		self.assertFalse(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Billing Details Required"}
			)
		)

	def test_a_team_is_not_asked_again_the_next_day(self):
		# The engine only suppresses a repeat for an hour, so a daily sweep would
		# mail every member of the team every day about the same missing field.
		self._grant(5000)
		self._create_server()

		settlement.run_billing_details_reminder()
		asked_again = settlement.run_billing_details_reminder()

		self.assertEqual(asked_again, 0)
		self.assertEqual(
			frappe.db.count(
				"Billing Notification Log", {"team": TEAM, "event_type": "Billing Details Required"}
			),
			1,
		)

	def test_a_team_asked_long_enough_ago_is_asked_again(self):
		self._grant(5000)
		self._create_server()
		settlement.run_billing_details_reminder()
		stale = frappe.utils.add_days(frappe.utils.now_datetime(), -settlement.REMINDER_EVERY_DAYS - 1)
		frappe.db.set_value(
			"Billing Notification Log",
			{"team": TEAM},
			"creation",
			stale,
			update_modified=False,
		)

		self.assertEqual(settlement.run_billing_details_reminder(), 1)

	def test_a_team_with_details_is_left_alone(self):
		complete_billing_profile(TEAM)
		self._create_server()

		settlement.run_billing_details_reminder()

		self.assertFalse(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Billing Details Required"}
			)
		)
