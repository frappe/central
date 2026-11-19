# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""AI billing across days and months: when the rate is fixed, credits carry, and reading catches up."""

from unittest.mock import patch

import frappe

from central.billing.revenue import exchange_rates, usage_recount
from central.billing.revenue.invoicing.generate import team_clusters
from central.billing.revenue.metering import metered_line_items_for_clusters
from central.billing.tests.test_ai_billing import (
	JUNE,
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
