# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The reads behind the reworked Billing Overview.

Three things worth pinning down. The forecast must carry its measured/estimated
split, because the whole point of the card is that a bill which is part guesswork
does not read like a bill. The next-payment outlook must warn only where the team's
own state entails failure, and never claim a charge will succeed. And the locked-price
read must not report a fallen catalog price as a negative saving.
"""

import frappe

from central.billing.api import dashboard
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_billing_subscription,
	make_plan,
	reset_gateway_roster,
	set_team_tier,
)

TEAM = "team-overview"
CLUSTER = "ap-south-1"
PLAN = "bundle-overview-test"


class OverviewBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": 3000}])
		reset_gateway_roster()
		self._purge()
		self.today = frappe.utils.getdate()
		self.month_start = frappe.utils.get_first_day(self.today)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Credit Ledger Entry", "Payment Method", "Tax Profile", "Billing Profile"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _provision(self, rate=3000):
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", rate, f"{self.month_start} 00:00:00", plan=PLAN)
		return sub


class TestForecastBasis(OverviewBase):
	def test_forecast_carries_the_measured_estimated_split(self):
		self._provision(rate=3000)

		fc = dashboard.get_forecast(TEAM)

		# A fixed bundle over elapsed days is arithmetic on a locked rate — a fact,
		# not an inference. Nothing here should read as an estimate.
		self.assertEqual(fc["measured"], 3000.0)
		self.assertEqual(fc["estimated"], 0.0)
		self.assertFalse(fc["has_estimates"])
		self.assertEqual(fc["measured"] + fc["estimated"], fc["subtotal"])

	def test_every_line_says_where_its_quantity_came_from(self):
		self._provision(rate=3000)

		fc = dashboard.get_forecast(TEAM)

		self.assertTrue(fc["line_items"])
		for line in fc["line_items"]:
			self.assertIn(line["basis"], ("Measured", "Estimated", "Assumed"))

	def test_a_stored_invoice_line_is_always_measured(self):
		# By the time an invoice is issued nothing about it is still inferred, so a
		# line item read off the document reports itself as a fact.
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": str(self.month_start),
				"period_end": str(frappe.utils.get_last_day(self.today)),
				"currency": "INR",
				"subtotal": 1000,
				"total": 1000,
				"items": [{"resource_type": "bundle", "plan": PLAN, "rate": 1000, "days": 30, "amount": 1000}],
			}
		).insert(ignore_permissions=True)

		detail = dashboard.get_invoice(invoice.name)

		self.assertEqual(detail["items"][0]["basis"], "Measured")


class TestNextPayment(OverviewBase):
	def test_no_payment_method_is_reported_as_a_blocker(self):
		self._provision(rate=3000)

		out = dashboard.get_next_payment(TEAM)

		self.assertEqual(out["amount"], 3000.0)
		self.assertFalse(out["will_auto_charge"])
		codes = [b["code"] for b in out["blockers"]]
		self.assertIn("no_settlement_source", codes)

	def test_a_blocker_says_what_to_do_about_it(self):
		# The engine's own wording is written for an operator reading a book of
		# teams. What reaches a customer has to tell them what to do.
		self._provision(rate=3000)

		blocker = dashboard.get_next_payment(TEAM)["blockers"][0]

		self.assertTrue(blocker["fix"])
		self.assertNotIn("dunning", blocker["fix"].lower())

	def test_a_bill_over_the_silent_ceiling_is_flagged_before_the_first(self):
		complete_billing_profile(TEAM, currency="INR")
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Auto Charge")
		# Tier cap under the bill: the charge path would refuse this off-session, so
		# the customer is told now rather than after a failed debit.
		set_team_tier(TEAM, max_spend=1000)
		self._provision(rate=3000)

		out = dashboard.get_next_payment(TEAM)

		self.assertIn("over_silent_threshold", [b["code"] for b in out["blockers"]])

	def test_nothing_due_is_not_a_blocker(self):
		out = dashboard.get_next_payment(TEAM)

		self.assertEqual(out["amount"], 0.0)

	def test_the_schedule_publishes_the_escalation_ladder(self):
		self._provision(rate=3000)

		schedule = dashboard.get_payment_schedule(TEAM)

		self.assertTrue(schedule["if_unpaid"])
		for stage in schedule["if_unpaid"]:
			self.assertIn("date", stage)
			self.assertIn("stage", stage)
		self.assertEqual(schedule["notices"], [])


class TestCycleCosts(OverviewBase):
	def test_cost_is_reported_per_resource(self):
		self._provision(rate=3000)

		out = dashboard.get_cycle_costs(TEAM)

		self.assertEqual(len(out["items"]), 1)
		self.assertEqual(out["items"][0]["amount"], 3000.0)
		self.assertEqual(out["total"], 3000.0)
		self.assertEqual(out["currency"], "INR")

	def test_nothing_running_costs_nothing(self):
		out = dashboard.get_cycle_costs(TEAM)

		self.assertEqual(out["items"], [])
		self.assertEqual(out["total"], 0.0)


class TestLockedPrices(OverviewBase):
	def test_a_rate_below_list_is_reported_as_a_saving(self):
		# Catalog says 3000; this segment locked at 2000 before a rise.
		self._provision(rate=2000)

		out = dashboard.get_locked_prices(TEAM)

		row = out["rows"][0]
		self.assertEqual(row["locked_rate"], 2000.0)
		self.assertEqual(row["list_rate"], 3000.0)
		self.assertEqual(row["saving"], 1000.0)
		self.assertFalse(row["above_list"])
		self.assertEqual(out["monthly_saving"], 1000.0)
		self.assertEqual(out["annual_saving"], 12000.0)
		self.assertEqual(out["protected_count"], 1)

	def test_a_fallen_catalog_price_is_never_a_negative_saving(self):
		# The lock cuts both ways: locked at 5000, catalog since down to 3000. The
		# customer is over list and is told so — not shown a saving of -2000.
		self._provision(rate=5000)

		out = dashboard.get_locked_prices(TEAM)

		row = out["rows"][0]
		self.assertEqual(row["saving"], 0.0)
		self.assertTrue(row["above_list"])
		self.assertEqual(row["above_list_by"], 2000.0)
		self.assertEqual(out["monthly_saving"], 0.0)
		self.assertEqual(out["protected_count"], 0)
		self.assertEqual(out["above_list_count"], 1)

	def test_the_locked_rate_is_what_the_subscription_list_quotes(self):
		# A grandfathered team must not be shown today's catalog rate as its price:
		# the open segment is what it will actually be billed (ADR 0010).
		self._provision(rate=2000)

		row = dashboard.list_subscriptions(TEAM)[0]

		self.assertEqual(row["monthly_rate"], 2000.0)
		self.assertTrue(row["resource_id"])


class TestReports(OverviewBase):
	"""The period-ranged reads behind Billing → Reports."""

	def _invoice(self, period_start, period_end, total=3000, paid=0, status="Paid", tax=0, tax_type="None"):
		return frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": status,
				"period_start": period_start,
				"period_end": period_end,
				"currency": "INR",
				"subtotal": total - tax,
				"output_tax_type": tax_type,
				"output_tax_amount": tax,
				"total": total,
				"amount_paid": paid,
				"expected_collection": total,
				"items": [
					{
						"resource_type": "bundle",
						"plan": PLAN,
						"cluster": CLUSTER,
						"rate": total,
						"days": 30,
						"amount": total - tax,
					}
				],
			}
		).insert(ignore_permissions=True)

	def test_history_reports_every_month_in_the_window(self):
		# A month with no invoice is a month with no spend, not a missing bar.
		self._invoice("2026-07-01", "2026-07-31", total=3000, paid=3000)

		out = dashboard.get_spend_history(TEAM, months=12)

		self.assertEqual(len(out["months"]), 12)
		self.assertEqual({m["month"] for m in out["months"]} & {"2026-07"}, {"2026-07"})
		july = next(m for m in out["months"] if m["month"] == "2026-07")
		self.assertEqual(july["total"], 3000.0)
		self.assertEqual(july["paid"], 3000.0)

	def test_history_breaks_spend_down_by_product_and_region(self):
		self._invoice("2026-07-01", "2026-07-31", total=3000, paid=3000)

		out = dashboard.get_spend_history(TEAM, months=12)

		self.assertEqual([r["label"] for r in out["by_product"]], ["VM Plans"])
		self.assertEqual(out["by_product"][0]["amount"], 3000.0)
		self.assertTrue(out["by_region"])

	def test_statement_separates_credits_from_payment(self):
		self._invoice("2026-07-01", "2026-07-31", total=3000, paid=3000)
		frappe.db.set_value(
			"Invoice",
			frappe.get_all("Invoice", {"team": TEAM}, pluck="name")[0],
			"credit_applied",
			1000,
		)

		out = dashboard.get_statement(TEAM, from_date="2026-01-01", to_date="2026-12-31")

		self.assertEqual(out["charged"], 3000.0)
		self.assertEqual(out["settled_by_credits"], 1000.0)
		self.assertEqual(out["settled_by_payment"], 3000.0)
		self.assertEqual(out["closing_outstanding"], 0.0)
		self.assertEqual(len(out["rows"]), 1)

	def test_statement_carries_what_was_owed_before_the_window(self):
		# An unpaid bill from before the range must not vanish, or the statement reads
		# as though the team started clean.
		self._invoice("2026-01-01", "2026-01-31", total=5000, status="Overdue")

		out = dashboard.get_statement(TEAM, from_date="2026-06-01", to_date="2026-12-31")

		self.assertEqual(out["opening_outstanding"], 5000.0)

	def test_tax_summary_never_calls_a_tax_None(self):
		# output_tax_type's "no tax" option is the literal string "None" — truthy, and
		# it must never reach a customer as the name of a tax.
		self._invoice("2026-07-01", "2026-07-31", total=3000, tax_type="None")

		out = dashboard.get_tax_summary(TEAM, from_date="2026-01-01", to_date="2026-12-31")

		self.assertEqual([b["tax_type"] for b in out["by_type"]], ["No tax"])
		self.assertTrue(out["is_working_paper"])

	def test_tax_summary_groups_by_the_mechanic_applied(self):
		self._invoice("2026-06-01", "2026-06-30", total=3540, tax=540, tax_type="GST")
		self._invoice("2026-07-01", "2026-07-31", total=3540, tax=540, tax_type="GST")

		out = dashboard.get_tax_summary(TEAM, from_date="2026-01-01", to_date="2026-12-31")

		gst = next(b for b in out["by_type"] if b["tax_type"] == "GST")
		self.assertEqual(gst["invoices"], 2)
		self.assertEqual(gst["tax"], 1080.0)
		self.assertEqual(out["total_tax"], 1080.0)

	def test_a_new_team_gets_a_full_empty_window_not_an_error(self):
		out = dashboard.get_spend_history(TEAM, months=12)

		self.assertEqual(len(out["months"]), 12)
		self.assertEqual(out["total"], 0.0)
		self.assertEqual(out["invoice_count"], 0)
		self.assertEqual(out["by_product"], [])
		self.assertEqual(dashboard.list_refunds(TEAM), [])

	def test_months_window_is_bounded(self):
		out = dashboard.get_spend_history(TEAM, months=999)

		self.assertEqual(len(out["months"]), 36)


class TestMandateRevokeOnRemoval(OverviewBase):
	"""Removing a mandate must withdraw it at the bank, not just from our table."""

	def _mandate(self):
		return frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": frappe.db.get_value("Payment Gateway", {"adapter_key": "razorpay"}, "name"),
				"method_type": "UPI Autopay",
				"status": "Active",
				"gateway_method_id": "token_e2e_mandate",
				"gateway_customer_id": "cust_e2e",
				"display_label": "UPI Autopay ···9999",
				"mandate_max_amount": 15000,
				"priority": 0,
				"is_default": 1,
			}
		).insert(ignore_permissions=True)

	def test_removing_a_mandate_revokes_it_at_the_gateway(self):
		from unittest.mock import patch

		from central.billing.payments import payments

		method = self._mandate()
		with patch("central.billing.payments.mandates.cancel_mandate") as revoke:
			out = payments.delete_payment_method(method.name)

		revoke.assert_called_once_with(method.name)
		self.assertTrue(out["mandate_revoked"])
		self.assertFalse(frappe.db.exists("Payment Method", method.name))

	def test_a_card_is_removed_without_a_mandate_call(self):
		from unittest.mock import patch

		from central.billing.payments import payments

		card = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": frappe.db.get_value("Payment Gateway", {"adapter_key": "stripe"}, "name"),
				"method_type": "Card",
				"status": "Active",
				"gateway_method_id": "pm_e2e_card",
				"display_label": "Visa ···4242",
				"priority": 0,
			}
		).insert(ignore_permissions=True)

		with patch("central.billing.payments.mandates.cancel_mandate") as revoke:
			out = payments.delete_payment_method(card.name)

		revoke.assert_not_called()
		self.assertFalse(out["mandate_revoked"])


class TestDeclineWording(OverviewBase):
	def test_a_known_decline_is_said_in_plain_language(self):
		from central.billing.payments import decline

		self.assertEqual(decline.customer_reason("expired_card"), "Your card has expired")
		self.assertEqual(decline.customer_reason("insufficient_funds"), "There wasn't enough balance")

	def test_an_unknown_code_never_leaks_the_gateway_string(self):
		# Vague but never wrong beats inventing a reason we do not have.
		from central.billing.payments import decline

		self.assertEqual(
			decline.customer_reason("some_new_provider_code"), "We couldn't complete this payment"
		)

	def test_an_ambiguous_failure_is_not_called_a_failure(self):
		from central.billing.payments import decline

		self.assertIn("still confirming", decline.customer_reason("timeout").lower())

	def test_payment_history_carries_the_plain_reason_only_for_failures(self):
		gateway = frappe.db.get_value("Payment Gateway", {"adapter_key": "stripe"}, "name")
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": str(self.month_start),
				"period_end": str(frappe.utils.get_last_day(self.today)),
				"currency": "INR",
				"subtotal": 1000,
				"total": 1000,
			}
		).insert(ignore_permissions=True)
		for status, code in (("Failed", "expired_card"), ("Captured", None)):
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"team": TEAM,
					"invoice": invoice.name,
					"gateway": gateway,
					"amount": 1000,
					"currency": "INR",
					"status": status,
					"failure_code": code,
					"idempotency_key": frappe.generate_hash(10),
				}
			).insert(ignore_permissions=True)

		rows = dashboard.list_payment_attempts(TEAM)

		failed = next(r for r in rows if r["status"] == "Failed")
		captured = next(r for r in rows if r["status"] == "Captured")
		self.assertEqual(failed["reason"], "Your card has expired")
		self.assertIsNone(captured["reason"])


class TestPaymentHistoryTime(OverviewBase):
	def test_history_reports_when_the_payment_happened_not_when_the_row_was_written(self):
		# `creation` is the insert time: for a backfilled or migrated attempt that is
		# the day it was imported, so every payment would read as though it happened
		# today. The list must carry the gateway's own timing.
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Paid",
				"period_start": "2026-03-01",
				"period_end": "2026-03-31",
				"currency": "INR",
				"subtotal": 1000,
				"total": 1000,
			}
		).insert(ignore_permissions=True)
		gateway = frappe.db.get_value("Payment Gateway", {"adapter_key": "stripe"}, "name")
		for when, retry in (("2026-03-01 09:00:00", 0), ("2026-03-02 09:00:00", 1)):
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"team": TEAM,
					"invoice": invoice.name,
					"gateway": gateway,
					"amount": 1000,
					"currency": "INR",
					"status": "Captured",
					"retry_number": retry,
					"initiated_at": when,
					"completed_at": when,
					"idempotency_key": frappe.generate_hash(10),
				}
			).insert(ignore_permissions=True)

		rows = dashboard.list_payment_attempts(TEAM)

		self.assertTrue(rows[0]["at"].startswith("2026-03-02"))
		self.assertTrue(rows[1]["at"].startswith("2026-03-01"))
		# Newest first on the resolved time, not on insert order.
		self.assertGreater(rows[0]["at"], rows[1]["at"])


class TestResizedInvoiceReadsAsASequence(OverviewBase):
	def test_lines_are_chronological_and_say_when_they_ran(self):
		# One server resized down and back inside a month bills as several segments.
		# They have to arrive in the order they happened and each say the window it
		# covers, or the customer is handed durations with no sequence.
		from central.billing.revenue.invoicing.lines import compute_line_items

		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", 9360, "2026-08-01 00:00:00", plan=PLAN)
		add_segment(sub, "Plan Changed", 6000, "2026-08-14 20:00:00", plan=PLAN)
		add_segment(sub, "Plan Changed", 12000, "2026-08-15 08:00:00", plan=PLAN)

		lines = compute_line_items(TEAM, CLUSTER, "2026-08-01", "2026-08-31")
		bundles = [ln for ln in lines if ln["resource_type"] == "bundle"]

		self.assertGreater(len(bundles), 3)
		starts = [ln["period_from"] for ln in bundles]
		self.assertEqual(starts, sorted(starts), "lines must arrive in the order they happened")
		for line in bundles:
			self.assertIsNotNone(line["period_from"])
			self.assertIsNotNone(line["period_to"])
			self.assertLess(line["period_from"], line["period_to"])

		# No gaps: each window picks up where the last left off, so the month reads
		# as one continuous story rather than disconnected fragments.
		for earlier, later in zip(bundles, bundles[1:], strict=False):
			self.assertEqual(earlier["period_to"], later["period_from"])

	def test_the_window_is_described_in_plain_dates(self):
		from central.billing.api.dashboard._shared import _billed_window

		daily = frappe._dict(
			unit="day",
			days=13,
			hours=None,
			charge_date=None,
			period_from="2026-08-01 00:00:00",
			period_to="2026-08-14 00:00:00",
		)
		hourly = frappe._dict(
			unit="hour",
			days=None,
			hours=4,
			charge_date="2026-08-14",
			period_from="2026-08-14 20:00:00",
			period_to="2026-08-15 00:00:00",
		)

		self.assertEqual(_billed_window(daily), "1–13 Aug")
		# Midnight closes the day it ends, so it reads 24:00 rather than 00:00.
		self.assertEqual(_billed_window(hourly), "14 Aug, 20:00–24:00")

	def test_a_line_without_a_window_still_says_how_long(self):
		# Invoices issued before the window was recorded keep working.
		from central.billing.api.dashboard._shared import _billed_window

		legacy = frappe._dict(
			unit="day", days=30, hours=None, charge_date=None, period_from=None, period_to=None
		)

		self.assertEqual(_billed_window(legacy), "30 day(s)")


class TestResizeLockDisclosure(OverviewBase):
	"""A resize re-prices at current rates (ADR 0010). The customer has to be told
	what that costs them BEFORE they confirm, not on the next invoice."""

	def _server(self, locked_rate):
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", locked_rate, f"{self.month_start} 00:00:00", plan=PLAN)
		return sub

	def test_a_rate_below_list_reports_what_the_resize_gives_up(self):
		from central.billing.api.dashboard.catalog import _lock_disclosure

		# Catalog lists this plan at 3000; this server locked in at 2000.
		self._server(2000)

		lock = _lock_disclosure(frappe.get_all("Subscription", {"team": TEAM}, pluck="name")[0], "INR")

		self.assertEqual(lock["locked_rate"], 2000.0)
		self.assertEqual(lock["list_rate"], 3000.0)
		self.assertEqual(lock["gives_up"], 1000.0)

	def test_a_rate_at_or_above_list_has_nothing_to_warn_about(self):
		from central.billing.api.dashboard.catalog import _lock_disclosure

		# Locked ABOVE today's list: resizing can only help, so no warning.
		self._server(5000)

		lock = _lock_disclosure(frappe.get_all("Subscription", {"team": TEAM}, pluck="name")[0], "INR")

		self.assertEqual(lock["gives_up"], 0.0)

	def test_the_resize_picker_carries_the_disclosure(self):
		from central.billing.api.dashboard.catalog import get_composed_config

		sub = self._server(2000)
		asset = frappe.db.get_value("Subscription", sub, "asset_id")

		config = get_composed_config(asset, TEAM)

		self.assertTrue(config["resizable"])
		self.assertEqual(config["lock"]["gives_up"], 1000.0)
