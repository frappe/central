# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""AI billing across days and months: when the rate is fixed, credits carry, and reading catches up."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.revenue import exchange_rates, usage_recount
from central.billing.revenue.invoicing.generate import team_clusters
from central.billing.revenue.metered_lines import MAXIMUM_DESCRIPTION, line_description
from central.billing.revenue.metering import metered_line_items_for_clusters
from central.billing.tests.test_ai_billing import (
	JUNE,
	TEAM_INR,
	TEAM_USD,
	AIBillingCase,
	rate_on,
	run_inline,
)


class TestAIBillingMonths(AIBillingCase):
	def recount(self, rate):
		with (
			patch.object(exchange_rates, "accounting_rate", return_value=rate),
			patch("frappe.enqueue", side_effect=run_inline),
		):
			usage_recount.recount_changed()

	def inr_rollup(self):
		return frappe.get_all(
			"Usage Rollup",
			filters={"team": TEAM_INR, "resource_type": "AI Usage", "superseded_by": ["is", "not set"]},
			fields=["name", "locked_rate", "rate_date"],
		)[0]

	def test_the_recount_keeps_an_earlier_rate_unlocked_until_the_firsts_rate_arrives(self):
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0})
		self.read("2026-06-10")
		self.recount(rate_on("2026-05-29", 83.5))
		rollup = self.inr_rollup()
		self.assertEqual((rollup.locked_rate, rollup.rate_date), (83.5, None))
		self.assertFalse(frappe.db.count("Monthly Exchange Rate", {"month": "2026-06-01"}))

		self.land(TEAM_INR, "2026-06-11", {"gpt-4o": 1.0})
		self.read("2026-06-11")
		self.recount(rate_on("2026-06-01", 84.1))
		rollup = self.inr_rollup()
		self.assertEqual((rollup.locked_rate, str(rollup.rate_date)), (84.1, "2026-06-01"))

		# Locked: a later change in the accounting system does not move it.
		self.land(TEAM_INR, "2026-06-12", {"gpt-4o": 1.0})
		self.read("2026-06-12")
		self.recount(rate_on("2026-06-01", 90))
		self.assertEqual(self.inr_rollup().locked_rate, 84.1)

	def test_a_worker_that_loses_the_race_returns_the_stored_rate(self):
		key = exchange_rates.month_key("USD", "INR", "2026-06-01")
		with patch.object(exchange_rates, "accounting_rate", return_value=rate_on("2026-06-01", 84.1)):
			exchange_rates.fix_month_rate("USD", "INR", "2026-06-01")
		found = exchange_rates._store(key, rate_on("2026-06-01", 90))
		self.assertEqual((found.rate, found.fixed), (84.1, True))

	def test_forecasts_and_rerating_see_ai_but_no_other_blank_cluster_usage(self):
		self.land(TEAM_USD, "2026-06-10", {"gpt-4o": 3.0})
		self.read("2026-06-10")
		self.recount(None)
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"team": TEAM_USD,
				"resource_id": "tokens-subject",
				"resource_type": "Tokens",
				"period_start": "2026-06-01",
				"period_end": "2026-06-30",
				"quantity": 5,
				"currency": "USD",
				"locked_rate": 1,
				"idempotency_key": "test-ai-billing-tokens",
			}
		).insert(ignore_permissions=True)
		lines = metered_line_items_for_clusters(TEAM_USD, team_clusters(TEAM_USD), *JUNE)
		self.assertEqual([(li["resource_type"], li["amount"]) for li in lines], [("AI Usage", 3.0)])

	def test_a_long_model_keeps_the_rate_in_the_line_description(self):
		rollup = frappe._dict(
			dimension="m" * 140, rate_date=datetime.date(2026, 6, 1), unit="USD", currency="INR"
		)
		description = line_description(rollup, 84.1)
		self.assertLessEqual(len(description), MAXIMUM_DESCRIPTION)
		self.assertTrue(description.endswith("rate of 2026-06-01"))
