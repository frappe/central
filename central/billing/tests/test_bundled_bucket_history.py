# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A server's backup bucket bills each past day on the bundle that day was on."""

import json
from unittest.mock import MagicMock, patch

import frappe

from central.billing.revenue import storage_bridge, usage_ledger, usage_recount
from central.billing.tests import test_bundled_buckets as base
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, make_metered_plan, make_plan

PAUSED_AT = "2026-06-02 12:00:00"


class TestBundledBucketHistory(IntegrationTestCase):
	# The fixture is the bundled-bucket one: a server whose plan includes 40 GB of storage.
	setUp = base.TestBundledBuckets.setUp
	read = base.TestBundledBuckets.read
	estimated_bundles = base.TestBundledBuckets.estimated_bundles
	transfer_day = base.TestBundledBuckets.transfer_day

	def read_page(self, day: str, gb: float) -> None:
		"""Run a page queued for `day`, after whatever changed since."""
		client = MagicMock()
		client.get_usage.return_value = {"usage": {"used_bytes": gb * base.GB}}
		with patch.object(storage_bridge.ObjectStorageClient, "from_region", return_value=client):
			storage_bridge.RegionRead("test-run", base.CLUSTER).start(1)
			storage_bridge.read_bundled_page("test-run", base.CLUSTER, [self.bucket], day=day)

	def stored_days(self) -> list:
		return frappe.get_all(
			"Usage Day",
			filters={"subject": self.bucket},
			fields=["day", "quantity", "included"],
			order_by="day asc",
		)

	def test_a_page_queued_before_a_pause_still_reads_its_day(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)
		self.read_page("2026-06-02", 100)
		[day] = self.stored_days()
		self.assertEqual((str(day.day), day.quantity, day.included), ("2026-06-02", 100, 40))

	def test_a_page_for_a_day_after_the_pause_reads_nothing(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)
		self.read_page("2026-06-03", 100)
		self.assertEqual(self.stored_days(), [])

	def test_only_a_servers_bucket_pages_carry_their_day(self):
		jobs = {"read_page": {base.CLUSTER: [["team-bucket"]]}, "read_bundled_page": {base.CLUSTER: [["vm"]]}}
		with patch.object(frappe, "enqueue") as enqueue:
			storage_bridge._enqueue_pages("run", jobs, frappe.utils.getdate("2026-06-02"))
		days = {call.args[0].rsplit(".", 1)[1]: call.kwargs.get("day") for call in enqueue.call_args_list}
		self.assertEqual(days, {"read_page": None, "read_bundled_page": "2026-06-02"})

	def compose(self, storage_gb: float, on: str) -> None:
		"""Resize the server onto a composed shape holding `storage_gb` of storage from `on`."""
		from central.billing.catalog.subscriptions import _resize_disk_choice, resize_composed_subscription

		_, rows, _ = _resize_disk_choice(base.VM_PLAN, None, "General", 120)
		rows = [{**row, "quantity": storage_gb} if row["resource_type"] == "Storage" else row for row in rows]
		# The spend cap is not under test.
		with patch("central.billing.catalog.subscriptions.enforce_headroom"):
			resize_composed_subscription(
				self.subscription, rows, "General", override_rate=1000, preset_plan=base.VM_PLAN
			)
		latest = frappe.get_all(
			"Subscription Change",
			filters={"subscription": self.subscription, "change_type": "Plan Changed"},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		frappe.db.set_value("Subscription Change", latest[0], "effective_at", on)

	def test_a_composed_day_before_a_resize_is_estimated_on_its_own_storage(self):
		self.compose(40, "2026-06-01 00:00:01")
		self.compose(200, "2026-06-10 12:00:00")
		self.read("2026-06-01", 100)
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.estimated_bundles(), [40])

	def test_a_composed_change_keeps_what_it_includes(self):
		self.compose(200, "2026-06-10 12:00:00")
		kept = frappe.get_all(
			"Subscription Change",
			filters={"subscription": self.subscription, "change_type": "Plan Changed"},
			pluck="included_resources",
		)
		storage = [row for row in json.loads(kept[0]) if row["resource_type"] == "Storage"]
		self.assertEqual([row["quantity"] for row in storage], [200])

	def test_a_resumed_composed_segment_keeps_what_it_included(self):
		from central.billing.catalog.subscriptions import reopen_paused_billing

		self.compose(200, "2026-06-01 00:00:01")
		add_segment(self.subscription, "Paused", 0, PAUSED_AT)
		with patch("central.billing.catalog.subscriptions.enforce_headroom"):
			reopen_paused_billing(self.subscription)
		kept = frappe.db.get_value(
			"Subscription Change",
			{"subscription": self.subscription, "change_type": "Resumed"},
			"included_resources",
		)
		self.assertIn({"resource_type": "Storage", "quantity": 200, "unit": "GB"}, json.loads(kept))

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
