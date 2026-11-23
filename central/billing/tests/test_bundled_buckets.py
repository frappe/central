# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A server's backup bucket bills on the server, for what it holds above the plan's storage."""

from unittest.mock import MagicMock, patch

import frappe

from central.billing.api.dashboard._shared import _describe_line, _qty
from central.billing.platform import invariants, readiness
from central.billing.revenue import metering, storage_bridge, usage_ledger, usage_recount
from central.billing.revenue.bundled_buckets import bundled_buckets
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.tests.utils import (
	DEFAULT_INCLUDES,
	_clear_metered_plans,
	add_segment,
	make_metered_plan,
	make_plan,
	seed_running_resource,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.integrations.object_storage import ObjectStorageNotFound
from central.services.doctype.team_service.team_service import bucket_name_for

TEAM = "team-bundled-bucket"
SERVER = "bundled-bucket-vm"
CLUSTER = "ap-south-1"
VM_PLAN = "bundled-bucket-vm-plan"
STORAGE_PLAN = "bundled-bucket-storage"
GB = 1_000_000_000


class TestBundledBuckets(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Virtual Machine", {"team": TEAM})
		self.addCleanup(frappe.db.delete, "Virtual Machine", {"team": TEAM})
		_clear_metered_plans("Storage", keep=STORAGE_PLAN)
		make_plan(
			STORAGE_PLAN,
			category="Remote Storage",
			includes=[{"resource_type": "Storage", "quantity": 0, "unit": "GB"}],
			rates=[{"currency": "INR", "cluster": "", "rate": 2.5}],
		)
		storage = {"resource_type": "Storage", "quantity": 40, "unit": "GB"}
		make_plan(VM_PLAN, includes=[*DEFAULT_INCLUDES, storage])
		self.subscription = seed_running_resource(TEAM, SERVER, CLUSTER, VM_PLAN)
		self.bucket = bucket_name_for(frappe.db.get_value("Team", TEAM, "tenant_id"), CLUSTER, SERVER)

	def read(self, day: str, gb: float | None):
		"""Read the bucket on `day` holding `gb`; None reads a bucket Cargo does not have."""
		client = MagicMock()
		if gb is None:
			client.get_usage.side_effect = ObjectStorageNotFound("no bucket")
		else:
			client.get_usage.return_value = {"usage": {"used_bytes": gb * GB}}
		with (
			patch.object(storage_bridge, "utc_today", return_value=frappe.utils.getdate(day)),
			patch.object(storage_bridge.ObjectStorageClient, "from_region", return_value=client),
		):
			storage_bridge.RegionRead("test-run", CLUSTER).start(1)
			storage_bridge.read_bundled_page("test-run", CLUSTER, [self.bucket])

	def days(self) -> list[float]:
		return frappe.get_all(
			"Usage Day", filters={"subject": self.bucket}, pluck="quantity", order_by="day asc"
		)

	def resize(self, gb: float, on: str) -> str:
		plan = make_plan(
			f"{VM_PLAN}-{gb}",
			includes=[*DEFAULT_INCLUDES, {"resource_type": "Storage", "quantity": gb, "unit": "GB"}],
		)
		frappe.db.set_value("Subscription", self.subscription, "plan", plan)
		add_segment(self.subscription, "Plan Changed", 1000, on, plan=plan)
		return plan

	def storage_lines(self) -> list:
		invoice = generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		return frappe.get_all(
			"Invoice Line Item",
			filters={"parent": invoice, "resource_type": "Storage"},
			fields=["subscription_resource", "quantity", "amount"],
		)

	def test_the_bucket_is_named_as_pilot_names_it(self):
		self.assertEqual(list(bundled_buckets()), [self.bucket])
		self.assertEqual(bundled_buckets()[self.bucket].included, 40)

	def test_a_recount_keeps_an_operators_corrected_allowance(self):
		self.read("2026-06-01", 100)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		[rollup] = frappe.get_all("Usage Rollup", filters={"resource_id": SERVER}, pluck="name")
		head = metering.override_terms(rollup, allowance=5, reason="test")
		self.read("2026-06-02", 130)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		quantity, allowance = frappe.db.get_value("Usage Rollup", head, ["quantity", "locked_allowance"])
		self.assertAlmostEqual(allowance, 5)
		self.assertAlmostEqual(quantity, 230 / 30)  # two days held, 100 then 130 GB

	def test_a_recount_still_counts_the_allowance_after_a_rate_correction(self):
		self.read("2026-06-01", 100)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		[rollup] = frappe.get_all("Usage Rollup", filters={"resource_id": SERVER}, pluck="name")
		head = metering.override_terms(rollup, rate=1.0, reason="test")
		self.read("2026-06-02", 130)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		self.assertAlmostEqual(frappe.db.get_value("Usage Rollup", head, "locked_allowance"), 80 / 30)

	def test_a_day_keeps_what_was_held_and_what_the_plan_included(self):
		self.read("2026-06-01", 30)
		[day] = frappe.get_all("Usage Day", filters={"subject": self.bucket}, fields=["quantity", "included"])
		self.assertEqual((day.quantity, day.included), (30, 40))

	def test_a_bucket_within_the_plan_bills_nothing(self):
		self.read("2026-06-01", 30)
		self.assertEqual(self.storage_lines(), [])

	def test_the_storage_above_the_plan_bills_on_the_server(self):
		for day in range(1, 31):
			self.read(f"2026-06-{day:02d}", 100)
		[line] = self.storage_lines()
		self.assertEqual(line.subscription_resource, SERVER)
		self.assertAlmostEqual(line.quantity, 60)  # 100 GB held, 40 GB included, all month
		self.assertAlmostEqual(line.amount, 150)  # 60 GB-months at 2.5

	def test_the_line_says_what_was_used_and_included(self):
		for day in range(1, 31):
			self.read(f"2026-06-{day:02d}", 100)
		self.storage_lines()
		[rollup] = frappe.get_all(
			"Usage Rollup", filters={"resource_id": SERVER}, fields=["quantity", "locked_allowance"]
		)
		self.assertAlmostEqual(rollup.quantity, 100)
		self.assertAlmostEqual(rollup.locked_allowance, 40)

	def test_each_day_bills_above_the_plan_it_was_on(self):
		for day in range(1, 16):
			self.read(f"2026-06-{day:02d}", 100)
		self.resize(200, "2026-06-16 00:00:00")
		for day in range(16, 31):
			self.read(f"2026-06-{day:02d}", 100)
		[line] = self.storage_lines()
		self.assertAlmostEqual(line.quantity, 30)  # 60 GB over for 15 of 30 days, then nothing over

	def test_a_resize_after_the_days_first_read_applies_that_day(self):
		self.read("2026-06-01", 100)
		self.resize(200, "2026-06-01 12:00:00")
		self.read("2026-06-01", 90)
		[day] = frappe.get_all("Usage Day", filters={"subject": self.bucket}, fields=["quantity", "included"])
		self.assertEqual((day.quantity, day.included), (100, 200))  # the day keeps its peak

	def test_each_months_line_says_what_its_own_plan_included(self):
		self.read("2026-06-01", 100)
		self.resize(10, "2026-07-01 00:00:00")
		self.read("2026-07-01", 100)
		details = [
			self.storage_detail(*month)
			for month in (("2026-06-01", "2026-06-30"), ("2026-07-01", "2026-07-31"))
		]
		self.assertIn(f"over {_qty(40 / 30)} included", details[0])
		self.assertIn(f"over {_qty(10 / 31)} included", details[1])

	def storage_detail(self, start: str, end: str, field: str = "detail") -> str:
		invoice = frappe.get_doc("Invoice", generate_team_invoice(TEAM, start, end))
		[line] = [li for li in invoice.items if li.resource_type == "Storage"]
		return _describe_line(TEAM, line, (invoice.period_start, invoice.period_end))[field]

	def test_the_storage_line_names_its_server(self):
		frappe.db.set_value("Virtual Machine", SERVER, "title", "Backups box")
		self.read("2026-06-01", 100)
		item = self.storage_detail("2026-06-01", "2026-06-30", field="item")
		self.assertTrue(item.endswith(" · Backups box"))

	def test_a_line_not_on_a_server_names_no_server(self):
		line = frappe._dict(resource_type="Storage", subscription_resource="team-svc-subject", quantity=1)
		self.assertNotIn(" · ", _describe_line(TEAM, line, ("2026-06-01", "2026-06-30"))["item"])

	def test_a_bucket_never_attached_reads_as_empty(self):
		self.read("2026-06-01", None)
		self.assertEqual(self.days(), [0])

	def test_a_paused_server_bills_nothing_for_its_bucket(self):
		add_segment(self.subscription, "Paused", 0, "2026-06-02 00:00:00", plan=VM_PLAN)
		self.assertEqual(bundled_buckets(), {})
		self.read("2026-06-03", 100)
		self.assertEqual(self.days(), [])

	def test_a_plan_without_storage_has_no_bucket_to_bill(self):
		frappe.db.delete("Plan Includes", {"parent": VM_PLAN, "resource_type": "Storage"})
		self.assertEqual(bundled_buckets(), {})

	def test_a_missed_day_is_estimated_like_a_team_bucket(self):
		self.read("2026-06-01", 100)
		# Paused since, but it was billing on the missed day.
		add_segment(self.subscription, "Paused", 0, "2026-06-10 00:00:00", plan=VM_PLAN)
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.days(), [100, 100])

	def test_a_paused_server_gets_no_estimate_for_its_paused_days(self):
		for day in range(1, 10):
			self.read(f"2026-06-{day:02d}", 100)
		add_segment(self.subscription, "Paused", 0, "2026-06-10 00:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Resumed", 1000, "2026-06-15 12:00:00", plan=VM_PLAN)
		usage_ledger.fill_missing_days("2026-06-18")
		days = frappe.get_all("Usage Day", filters={"subject": self.bucket}, pluck="day", order_by="day")
		self.assertEqual([d.day for d in days], [*range(1, 10), 15])  # resumed on the 15th, which bills

	def test_a_server_resumed_after_a_pause_is_estimated_from_its_last_reading(self):
		for day in range(1, 6):
			self.read(f"2026-06-{day:02d}", 100)
		add_segment(self.subscription, "Paused", 0, "2026-06-06 00:00:00", plan=VM_PLAN)
		bigger = make_plan(
			f"{VM_PLAN}-resumed",
			includes=[*DEFAULT_INCLUDES, {"resource_type": "Storage", "quantity": 200, "unit": "GB"}],
		)
		add_segment(self.subscription, "Resumed", 1000, "2026-06-10 12:00:00", plan=bigger)
		usage_ledger.fill_missing_days("2026-06-13")
		days = frappe.get_all("Usage Day", filters={"subject": self.bucket}, pluck="day", order_by="day")
		self.assertEqual([d.day for d in days], [1, 2, 3, 4, 5, 10])  # the paused days stay empty
		self.assertEqual(self.estimated_bundles(), [200])

	def estimated_bundles(self) -> list[float]:
		return frappe.get_all(
			"Usage Day", filters={"subject": self.bucket, "estimated": 1}, pluck="included", order_by="day"
		)

	def test_an_estimated_day_carries_the_bundle_of_its_own_day(self):
		self.read("2026-06-01", 100)
		self.resize(200, "2026-06-02 12:00:00")
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.estimated_bundles(), [200])

	def test_an_estimated_day_takes_the_plan_it_was_on_not_todays(self):
		self.read("2026-06-01", 100)
		self.resize(200, "2026-06-10 12:00:00")
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.estimated_bundles(), [40])

	def test_a_server_resized_off_storage_is_still_estimated_for_its_storage_days(self):
		self.read("2026-06-01", 100)
		self.resize_off_storage("2026-06-10 12:00:00")
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.days(), [100, 100])

	def resize_off_storage(self, on: str):
		plan = make_plan(f"{VM_PLAN}-no-storage", includes=DEFAULT_INCLUDES)
		frappe.db.set_value("Subscription", self.subscription, "plan", plan)
		add_segment(self.subscription, "Plan Changed", 1000, on, plan=plan)

	def test_a_day_resized_off_storage_at_noon_is_estimated_on_its_morning_plan(self):
		self.read("2026-06-01", 100)
		self.resize_off_storage("2026-06-02 12:00:00")
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.estimated_bundles(), [40])

	def test_a_composed_disk_resize_keeps_the_bucket_and_its_storage(self):
		from central.billing.catalog.subscriptions import _resize_disk_choice, resize_composed_subscription

		_, rows, _ = _resize_disk_choice(VM_PLAN, None, "General", 120)
		# A preset grown past its disk keeps its bundle price plus the extra disk; the spend cap is not under test.
		with patch("central.billing.catalog.subscriptions.enforce_headroom"):
			resize_composed_subscription(
				self.subscription, rows, "General", override_rate=1000, preset_plan=VM_PLAN
			)
		self.assertIsNone(frappe.db.get_value("Subscription", self.subscription, "plan"))
		self.assertEqual(bundled_buckets()[self.bucket].included, 40)

	def test_a_server_resized_onto_a_storage_plan_is_read_now(self):
		from central.billing.catalog.subscriptions import change_plan

		self.resize_off_storage("2026-06-01 06:00:00")
		self.assertEqual(bundled_buckets(), {})
		change_plan(self.subscription, VM_PLAN)
		self.assertEqual(bundled_buckets()[self.bucket].included, 40)

	def test_a_server_paused_partway_through_a_day_is_estimated_for_it(self):
		self.read("2026-06-01", 100)
		add_segment(self.subscription, "Paused", 0, "2026-06-02 12:00:00", plan=VM_PLAN)
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.days(), [100, 100])

	def test_a_server_billing_only_midday_is_estimated_for_that_day(self):
		self.read("2026-06-01", 100)
		add_segment(self.subscription, "Paused", 0, "2026-06-01 20:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Resumed", 1000, "2026-06-02 10:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Paused", 0, "2026-06-02 20:00:00", plan=VM_PLAN)
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.days(), [100, 100])

	def test_a_day_resized_then_paused_is_estimated_on_the_new_plan(self):
		self.read("2026-06-01", 100)
		self.resize(200, "2026-06-02 10:00:00")
		add_segment(self.subscription, "Paused", 0, "2026-06-02 20:00:00", plan=VM_PLAN)
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(self.estimated_bundles(), [200])

	def test_a_reading_without_a_bundle_keeps_the_stored_one(self):
		self.read("2026-06-01", 100)
		[stored] = frappe.get_all(
			"Usage Day", filters={"subject": self.bucket}, fields=list(usage_ledger._DAY_FIELDS)
		)
		del stored["included"]
		later = frappe.utils.add_to_date(stored.as_of, hours=1)
		usage_ledger.write_days([{**stored, "quantity": 120, "as_of": later}])
		[day] = frappe.get_all("Usage Day", filters={"subject": self.bucket}, fields=["quantity", "included"])
		self.assertEqual((day.quantity, day.included), (120, 40))

	def test_an_older_reading_does_not_bring_back_an_older_bundle(self):
		self.read("2026-06-01", 100)
		[stored] = frappe.get_all(
			"Usage Day", filters={"subject": self.bucket}, fields=list(usage_ledger._DAY_FIELDS)
		)
		earlier = frappe.utils.add_to_date(stored.as_of, hours=-1)
		for quantity in (120, 50):
			usage_ledger.write_days([{**stored, "quantity": quantity, "included": 10, "as_of": earlier}])
		[day] = frappe.get_all("Usage Day", filters={"subject": self.bucket}, fields=["quantity", "included"])
		self.assertEqual((day.quantity, day.included), (120, 40))  # the peak rises, the bundle stays

	def test_a_bundle_corrected_to_nothing_is_cleared_on_recount(self):
		self.read("2026-06-01", 100)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		frappe.db.set_value("Usage Day", {"subject": self.bucket}, "included", 0)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		[allowance] = frappe.get_all(
			"Usage Rollup", filters={"resource_id": SERVER}, pluck="locked_allowance"
		)
		self.assertEqual(allowance, 0)

	def test_a_grandfathered_server_meter_keeps_its_locked_allowance(self):
		make_metered_plan("bundled-bucket-transfer", resource_type="Transfer")
		plan = make_plan(
			f"{VM_PLAN}-transfer",
			includes=[*DEFAULT_INCLUDES, {"resource_type": "Transfer", "quantity": 500, "unit": "GB"}],
		)
		frappe.db.set_value("Subscription", self.subscription, "plan", plan)
		add_segment(self.subscription, "Plan Changed", 1000, "2026-06-01 00:00:01", plan=plan)
		for day in ("2026-06-01", "2026-06-02"):
			usage_ledger.write_days([self.transfer_day(day)])
			usage_recount.recount_month(self.subscription, "Transfer", "2026-06-01")
		[allowance] = frappe.get_all(
			"Usage Rollup",
			filters={"resource_id": SERVER, "resource_type": "Transfer"},
			pluck="locked_allowance",
		)
		self.assertEqual(allowance, 500)

	def transfer_day(self, day: str) -> dict:
		return {
			"service": "bundled-bucket-transfer",
			"meter": "transfer",
			"subject": SERVER,
			"dimension": "",
			"day": day,
			"aggregation": "Sum",
			"team": TEAM,
			"subscription": self.subscription,
			"resource_type": "Transfer",
			"quantity": 100,
			"unit": "GB",
			"as_of": f"{day} 12:00:00",
		}

	def flagged(self, today: str) -> list:
		frappe.db.set_value("Virtual Machine", SERVER, "creation", "2026-06-01", update_modified=False)
		with patch.object(usage_ledger, "utc_today", return_value=frappe.utils.getdate(today)):
			return [v.subject for v in invariants.audit(only="M1", checks=readiness.CHECKS)]

	def test_a_bucket_with_no_usage_for_yesterday_is_flagged(self):
		self.assertIn(self.subscription, self.flagged("2026-06-05"))

	def test_a_server_paused_yesterday_is_not_flagged(self):
		add_segment(self.subscription, "Paused", 0, "2026-06-04 00:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Resumed", 1000, "2026-06-05 12:00:00", plan=VM_PLAN)
		self.assertNotIn(self.subscription, self.flagged("2026-06-05"))

	def test_a_server_paused_partway_through_yesterday_is_flagged(self):
		add_segment(self.subscription, "Paused", 0, "2026-06-04 12:00:00", plan=VM_PLAN)
		self.assertIn(self.subscription, self.flagged("2026-06-05"))

	def test_a_server_resized_off_storage_at_noon_yesterday_is_flagged(self):
		self.resize_off_storage("2026-06-04 12:00:00")
		self.assertIn(self.subscription, self.flagged("2026-06-05"))

	def test_a_server_billing_only_midday_yesterday_is_flagged(self):
		add_segment(self.subscription, "Paused", 0, "2026-06-03 12:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Resumed", 1000, "2026-06-04 10:00:00", plan=VM_PLAN)
		add_segment(self.subscription, "Paused", 0, "2026-06-04 20:00:00", plan=VM_PLAN)
		self.assertIn(self.subscription, self.flagged("2026-06-05"))


class TestBundleCount(IntegrationTestCase):
	def day(self, on: str, quantity: float, included: float, aggregation: str = "Sum"):
		return frappe._dict(day=on, quantity=quantity, included=included, aggregation=aggregation)

	def test_a_used_up_amount_bills_the_month_above_its_bundle(self):
		days = [self.day(f"2026-06-{d:02d}", 0.4, 10) for d in range(1, 31)]
		self.assertAlmostEqual(usage_recount._billable(days, 12), 2)  # 12 TB used, 10 TB included

	def test_a_bundle_scales_with_the_days_its_plan_ran(self):
		days = [self.day(f"2026-06-{d:02d}", 0.4, 10) for d in range(16, 31)]
		self.assertAlmostEqual(usage_recount._billable(days, 6), 1)  # 15 of 30 days give 5 TB

	def test_a_held_amount_bills_each_day_above_its_bundle(self):
		days = [self.day("2026-06-01", 3, 1, "Level"), self.day("2026-06-02", 0, 1, "Level")]
		# The 2nd day's unused address does not cover the 1st day's two extra ones.
		self.assertAlmostEqual(usage_recount._billable(days, 3 / 30), 2 / 30)

	def test_only_a_month_with_a_bundle_counts_one(self):
		days = [self.day("2026-06-01", 3, 0, "Level")]
		meter = frappe._dict(on_server=False, resource_type="Storage")
		self.assertEqual(usage_recount._bundle(meter, days, 0.1), {})
		bundled = [self.day("2026-06-01", 3, 1, "Level")]
		self.assertAlmostEqual(usage_recount._bundle(meter, bundled, 0.1)["counted_allowance"], 1 / 30)


class TestStoragePrice(IntegrationTestCase):
	def setUp(self):
		self.plan = frappe.db.get_value(
			"Plan", {"title": "Object Storage Plan", "category": "Remote Storage", "is_active": 1}, "name"
		) or make_plan(
			"object-storage-price-test",
			title="Object Storage Plan",
			category="Remote Storage",
			sub_category="Backups",
			includes=[{"resource_type": "Storage", "quantity": 0, "unit": "GB"}],
			rates=[],
		)
		from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates

		self.addCleanup(set_catalog_rates, "Plan", self.plan, get_catalog_rates("Plan", self.plan))

	def rates(self) -> dict:
		rows = frappe.get_all(
			"Catalog Rate",
			filters={"priced_doctype": "Plan", "priced_for": self.plan},
			fields=["currency", "rate"],
		)
		return {row.currency: row.rate for row in rows}

	def test_the_patch_prices_storage_and_keeps_a_rate_already_set(self):
		from central.billing.catalog.pricing import set_catalog_rates
		from central.patches.v0_0 import price_object_storage

		set_catalog_rates("Plan", self.plan, [{"currency": "USD", "rate": 0.03}])
		price_object_storage.execute()
		self.assertEqual(self.rates(), {"USD": 0.03, "INR": 2.5})
