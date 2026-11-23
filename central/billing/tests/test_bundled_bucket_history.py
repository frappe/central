# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A server's backup bucket bills each past day on the bundle that day was on."""

import frappe

from central.billing.revenue import usage_ledger, usage_recount
from central.billing.tests import test_bundled_buckets as base
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import make_metered_plan

PAUSED_AT = "2026-06-02 12:00:00"


class TestBundledBucketHistory(IntegrationTestCase):
	# The fixture is the bundled-bucket one: a server whose plan includes 40 GB of storage.
	setUp = base.TestBundledBuckets.setUp
	read = base.TestBundledBuckets.read
	estimated_bundles = base.TestBundledBuckets.estimated_bundles
	transfer_day = base.TestBundledBuckets.transfer_day

	def test_a_meter_that_carried_a_bundle_clears_it_once_its_days_carry_none(self):
		make_metered_plan("bundled-bucket-transfer", resource_type="Transfer")
		usage_ledger.write_days([{**self.transfer_day("2026-06-01"), "included": 500}])
		usage_recount.recount_month(self.subscription, "Transfer", "2026-06-01")
		# The bundled day is billed; the day still to bill carries no bundle.
		frappe.db.set_value(
			"Usage Day", {"subject": base.SERVER, "resource_type": "Transfer"}, "invoice", "X"
		)
		usage_ledger.write_days([self.transfer_day("2026-06-02")])
		usage_recount.recount_month(self.subscription, "Transfer", "2026-06-01")
		[allowance] = frappe.get_all(
			"Usage Rollup",
			filters={"resource_id": base.SERVER, "resource_type": "Transfer"},
			pluck="locked_allowance",
		)
		self.assertEqual(allowance, 0)

	def test_a_meter_that_never_carried_a_bundle_keeps_its_plans_allowance(self):
		make_metered_plan("bundled-bucket-transfer", resource_type="Transfer")
		usage_ledger.write_days([self.transfer_day("2026-06-01")])
		meter = usage_recount._meter(self.subscription, "Transfer")
		self.assertEqual(usage_recount._bundle(meter, [], 0), {})
