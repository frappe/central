# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Storage usage is kept per bucket per UTC day as the day's peak, and billed as the GB-month."""

from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.doctype.billing_run_team.billing_run_team import INVOICED, record_outcome
from central.billing.platform import invariants, readiness
from central.billing.revenue import storage_bridge, usage_ledger, usage_recount
from central.billing.revenue.invoicing.generate import generate_team_invoice, team_clusters
from central.billing.revenue.invoicing.lifecycle import cancel_invoice, reissue_invoice
from central.billing.revenue.metering import ingest_rollup
from central.billing.tests.test_credits import run_workers
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	complete_billing_profile,
	ensure_team,
	give_team_a_card,
	make_plan,
)
from central.services.doctype.service.service import STORAGE_METER, STORAGE_SERVICE
from central.services.doctype.team_service.team_service import TeamService

TEAM = "team-usage-ledger"
CLUSTER = "ap-south-1"
PLAN = "usage-ledger-plan"
BUCKET = "team-usage-ledger-bucket"
GB = 1_000_000_000


def on_own_connection(fn) -> None:
	"""Run `fn` and commit it on a second database connection, as another worker would."""
	[outcome] = run_workers(1, lambda _i: fn()).values()
	if outcome != "ok":
		raise AssertionError(f"the other worker failed: {outcome}")


def read_one_page(names: list[str], run: str = "test-run") -> int:
	storage_bridge.RegionRead(run, CLUSTER).start(1)
	return storage_bridge.read_page(run, CLUSTER, names)


class TestUsageLedger(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Team Service", {"team": TEAM})
		self.addCleanup(frappe.db.delete, "Team Service", {"team": TEAM})
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		give_team_a_card(TEAM)
		_clear_metered_plans("Storage", keep=PLAN)
		make_plan(
			PLAN,
			category="Remote Storage",
			includes=[{"resource_type": "Storage", "quantity": 0, "unit": "GB"}],
			rates=[{"currency": "INR", "cluster": CLUSTER, "rate": 2}],
		)
		self.subscription = provision_service_subscription(
			TEAM, PLAN, cluster=CLUSTER, start_date="2026-06-01"
		)["subscription"]
		self.bucket = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": TEAM,
				"add_on_service": "storage",
				"region": CLUSTER,
				"bucket_name": BUCKET,
				"external_id": BUCKET,
				"status": "Active",
				"subscription": self.subscription,
			}
		)
		self.bucket.db_insert()  # Skips before_insert, which would create the bucket in Cargo.

	def read(self, day: str, gb: float):
		with (
			patch.object(storage_bridge, "utc_today", return_value=frappe.utils.getdate(day)),
			patch(
				"central.services.doctype.team_service.team_service.TeamService.get_usage",
				return_value={"used_bytes": gb * GB},
			),
		):
			read_one_page([self.bucket.name])

	def days(self, **filters):
		return frappe.get_all(
			"Usage Day",
			filters={"team": TEAM, **filters},
			fields=["day", "quantity", "estimated", "invoice"],
			order_by="day asc",
		)

	def rollup(self, month: str):
		usage_recount.recount_month(self.subscription, "Storage", month)
		return frappe.db.get_value(
			"Usage Rollup",
			{"team": TEAM, "resource_type": "Storage", "period_start": month},
			["quantity", "invoice"],
			as_dict=True,
		)

	def test_a_day_keeps_its_peak(self):
		for gb in (10, 50, 20):
			self.read("2026-06-01", gb)
		[day] = self.days()
		self.assertEqual(day.quantity, 50)

	def test_a_line_that_loses_the_insert_race_still_lands(self):
		self.read("2026-06-01", 10)
		existing = usage_ledger._existing_days
		calls = []

		def missed_first(rows, **kwargs):
			calls.append(rows)
			return {} if len(calls) == 1 else existing(rows, **kwargs)

		with patch.object(usage_ledger, "_existing_days", side_effect=missed_first):
			self.read("2026-06-01", 40)
		self.assertEqual([d.quantity for d in self.days()], [40])

	def test_a_day_another_worker_committed_after_this_snapshot_still_lands(self):
		meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)

		def line(gb: float) -> dict:
			day = frappe.utils.getdate("2026-06-01")
			return meter.get_day_row(self.bucket, day, gb * GB, as_of=frappe.utils.now_datetime())

		first = line(10)
		frappe.get_all("Usage Day", limit=1)  # Opens this transaction's snapshot first.
		on_own_connection(lambda: usage_ledger.write_days([first]))
		self.addCleanup(
			on_own_connection, lambda: frappe.db.delete("Usage Day", {"subject": first["subject"]})
		)
		# Ends this transaction first, so the cleanup is not waiting on its row lock.
		self.addCleanup(frappe.db.rollback)

		self.assertEqual(usage_ledger.write_days([line(40)]), 1)
		self.assertEqual([d.quantity for d in self.days()], [40])

	def test_a_stale_read_never_lowers_a_peak(self):
		self.read("2026-06-01", 50)
		existing = usage_ledger._existing_days

		def stale(rows, **kwargs):
			return {key: frappe._dict(row, quantity=10) for key, row in existing(rows, **kwargs).items()}

		with patch.object(usage_ledger, "_existing_days", side_effect=stale):
			self.read("2026-06-01", 30)
		self.assertEqual([d.quantity for d in self.days()], [50])

	def test_a_usage_day_cannot_be_changed_by_hand(self):
		self.read("2026-06-01", 30)
		day = frappe.get_doc("Usage Day", {"team": TEAM})
		day.quantity = 1
		with self.assertRaises(frappe.PermissionError):
			day.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Usage Day", day.name, ignore_permissions=True)

	def test_a_rerun_writes_no_second_row(self):
		self.read("2026-06-01", 30)
		self.read("2026-06-01", 30)
		self.assertEqual(len(self.days()), 1)

	def test_the_month_is_the_sum_of_daily_peaks_over_its_days(self):
		self.read("2026-06-01", 30)
		self.read("2026-06-02", 60)
		self.assertAlmostEqual(self.rollup("2026-06-01").quantity, 3.0)  # (30 + 60) / 30 days

	def test_an_emptied_bucket_bills_the_peak_of_that_day_and_nothing_after(self):
		self.read("2026-06-01", 40)
		self.read("2026-06-01", 0)
		self.read("2026-06-02", 0)
		self.assertAlmostEqual(self.rollup("2026-06-01").quantity, 40 / 30)

	def test_a_missed_day_takes_the_last_reading_marked_estimated(self):
		self.read("2026-06-01", 30)
		usage_ledger.fill_missing_days("2026-06-05")
		estimated = self.days(day="2026-06-02")
		self.assertEqual([(d.quantity, d.estimated) for d in estimated], [(30, 1)])

	def test_a_late_reading_replaces_the_estimate(self):
		self.read("2026-06-01", 30)
		usage_ledger.fill_missing_days("2026-06-05")
		self.read("2026-06-02", 10)
		[day] = self.days(day="2026-06-02")
		self.assertEqual((day.quantity, day.estimated), (10, 0))

	def test_a_deleted_bucket_is_not_estimated(self):
		self.read("2026-06-01", 30)
		frappe.db.delete("Team Service", {"name": self.bucket.name})
		usage_ledger.fill_missing_days("2026-06-05")
		self.assertEqual(len(self.days()), 1)

	def test_a_day_belongs_to_the_month_of_its_utc_date(self):
		self.read("2026-06-30", 30)
		self.read("2026-07-01", 62)
		self.assertAlmostEqual(self.rollup("2026-06-01").quantity, 1.0)
		self.assertAlmostEqual(self.rollup("2026-07-01").quantity, 2.0)

	def test_the_invoice_bills_the_gb_month_and_marks_what_it_billed(self):
		for day in range(1, 31):
			self.read(f"2026-06-{day:02d}", 100)
		invoice = generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		storage = frappe.get_all(
			"Invoice Line Item", filters={"parent": invoice, "resource_type": "Storage"}, pluck="amount"
		)
		self.assertAlmostEqual(sum(storage), 200.0)  # 100 GB-months at 2 a GB-month
		self.assertEqual({d.invoice for d in self.days()}, {invoice})

	def test_a_day_that_arrives_after_its_month_was_billed_goes_on_the_next_month(self):
		for day in range(1, 30):
			self.read(f"2026-06-{day:02d}", 30)
		generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		self.read("2026-06-30", 30)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		self.assertAlmostEqual(self.rollup("2026-07-01").quantity, 1.0)  # 30 / 30 days of June

	def storage_billed(self, invoice: str) -> float:
		return sum(
			frappe.get_all(
				"Invoice Line Item", filters={"parent": invoice, "resource_type": "Storage"}, pluck="amount"
			)
		)

	def test_a_reissue_bills_the_days_of_the_cancelled_invoice(self):
		self.read("2026-06-01", 30)
		invoice = generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		reissued = reissue_invoice(invoice, reason="test")
		self.assertAlmostEqual(self.storage_billed(reissued), self.storage_billed(invoice))
		self.assertEqual({d.invoice for d in self.days()}, {reissued})

	def test_a_cancel_without_reissue_keeps_its_days_billed(self):
		self.read("2026-06-01", 30)
		invoice = generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		cancel_invoice(invoice, reason="test")
		self.assertEqual({d.invoice for d in self.days()}, {invoice})
		self.assertEqual(self.rollup("2026-06-01").invoice, invoice)

	def test_a_month_below_the_minimum_goes_on_the_next_invoice(self):
		self.read("2026-06-01", 30)  # 1 GB-month of June, 2 INR
		with patch("central.billing.settings.minimum_invoice_amount", return_value=50):
			self.assertIsNone(generate_team_invoice(TEAM, "2026-06-01", "2026-06-30"))
			for day in range(1, 32):
				self.read(f"2026-07-{day:02d}", 100)
			invoice = generate_team_invoice(TEAM, "2026-07-01", "2026-07-31")
		self.assertAlmostEqual(self.storage_billed(invoice), 202.0)
		self.assertEqual({d.invoice for d in self.days()}, {invoice})

	def test_a_late_day_of_a_month_invoiced_without_it_goes_on_the_next_invoice(self):
		record_outcome(TEAM, "2026-06-30", INVOICED)
		self.read("2026-06-30", 30)
		usage_recount.recount_month(self.subscription, "Storage", "2026-06-01")
		for day in range(1, 32):
			self.read(f"2026-07-{day:02d}", 100)
		invoice = generate_team_invoice(TEAM, "2026-07-01", "2026-07-31")
		self.assertAlmostEqual(self.storage_billed(invoice), 202.0)  # 1 GB-month of June, 100 of July
		self.assertEqual({d.invoice for d in self.days()}, {invoice})

	def test_a_day_written_while_the_invoice_drafts_stays_unbilled_and_carries(self):
		self.read("2026-06-01", 30)
		recount_team = usage_recount.recount_team

		def recount_then_write(team, period_end):
			counted = recount_team(team, period_end)
			self.read("2026-06-02", 30)
			return counted

		with patch.object(usage_recount, "recount_team", side_effect=recount_then_write):
			invoice = generate_team_invoice(TEAM, "2026-06-01", "2026-06-30")
		self.assertAlmostEqual(self.storage_billed(invoice), 2.0)
		self.assertEqual([d.invoice for d in self.days()], [invoice, None])
		self.assertAlmostEqual(self.rollup("2026-07-01").quantity, 1.0)  # 30 / 30 days of June

	def test_the_hourly_recount_picks_up_changed_months(self):
		frappe.db.set_default(usage_recount.WATERMARK, "2000-01-01 00:00:00")
		self.read("2026-06-01", 30)
		with patch(
			"frappe.enqueue",
			side_effect=lambda method, **kwargs: usage_recount.recount_page(kwargs["months"]),
		):
			usage_recount.recount_changed()
		quantity = frappe.db.get_value(
			"Usage Rollup", {"team": TEAM, "period_start": "2026-06-01"}, "quantity"
		)
		self.assertAlmostEqual(quantity, 1.0)

	def test_the_hourly_recount_sees_a_day_that_committed_after_its_last_scan(self):
		frappe.db.set_default(usage_recount.WATERMARK, "2026-06-02 10:00:00")
		self.read("2026-06-01", 30)
		frappe.db.set_value("Usage Day", {"team": TEAM}, "landed_at", "2026-06-02 09:58:00")
		with patch(
			"frappe.enqueue",
			side_effect=lambda method, **kwargs: usage_recount.recount_page(kwargs["months"]),
		):
			usage_recount.recount_changed(now="2026-06-02 11:00:00")
		quantity = frappe.db.get_value(
			"Usage Rollup", {"team": TEAM, "period_start": "2026-06-01"}, "quantity"
		)
		self.assertAlmostEqual(quantity, 1.0)

	def test_billed_days_past_thirteen_months_are_pruned(self):
		self.read("2025-03-01", 30)
		self.read("2025-03-02", 30)
		frappe.db.set_value("Usage Day", {"team": TEAM, "day": "2025-03-01"}, "invoice", "INV-OLD")
		usage_ledger.prune_old_days("2026-06-15")
		self.assertEqual([str(d.day) for d in self.days()], ["2025-03-02"])

	def test_the_deploy_carries_only_the_days_before_the_first_reading(self):
		from central.patches.v0_0 import start_usage_day_ledger as patch_module

		service_subject = frappe.db.get_value("Subscription", self.subscription, "service_subject")
		ingest_rollup(
			{
				"idempotency_key": f"old-storage::{service_subject}",
				"resource_id": service_subject,
				"resource_type": "Storage",
				"meter_type": "Gauge",
				"team": TEAM,
				"cluster": CLUSTER,
				"currency": "INR",
				"period_start": "2026-06-01",
				"period_end": "2026-06-30",
				"quantity": 10,  # GiB-month over the 5 days the old job read
				"unit": "GB",
				"sequence": 5,
			}
		)
		with patch.object(patch_module, "utc_today", return_value=frappe.utils.getdate("2026-06-04")):
			patch_module._carry_this_month()
		days = self.days()
		self.assertEqual([str(d.day) for d in days], ["2026-06-01", "2026-06-02", "2026-06-03"])
		self.assertAlmostEqual(days[0].quantity, 60 * 1024**3 / GB, places=4)

	def test_a_service_region_counts_as_a_team_cluster(self):
		self.assertIn(CLUSTER, team_clusters(TEAM))

	def unread_buckets(self, today: str) -> list:
		with patch.object(usage_ledger, "utc_today", return_value=frappe.utils.getdate(today)):
			return [
				v
				for v in invariants.audit(only="M1", checks=readiness.CHECKS)
				if v.subject == self.subscription
			]

	def test_a_bucket_with_no_usage_for_yesterday_is_flagged(self):
		frappe.db.set_value("Team Service", self.bucket.name, "creation", "2026-06-01", update_modified=False)
		self.assertEqual(len(self.unread_buckets("2026-06-05")), 1)

	def test_a_bucket_made_after_yesterday_is_not_flagged(self):
		frappe.db.set_value(
			"Team Service", self.bucket.name, "creation", "2026-06-05 12:00", update_modified=False
		)
		self.assertEqual(self.unread_buckets("2026-06-05"), [])

	def broken_bucket(self, suffix: str) -> str:
		broken = frappe.get_doc({**self.bucket.as_dict(), "name": None, "bucket_name": f"{BUCKET}-{suffix}"})
		broken.external_id = broken.bucket_name
		broken.db_insert()
		return broken.name

	def new_region_logs(self, read) -> list[str]:
		"""Run `read` with every bucket but the test's own failing, and return the Error Logs it wrote."""

		def usage(bucket):
			if bucket.name != self.bucket.name:
				raise frappe.ValidationError("Cargo is down")
			return {"used_bytes": 30 * GB}

		region_logs = {"reference_doctype": "Region", "reference_name": CLUSTER}
		before = set(frappe.get_all("Error Log", filters=region_logs, pluck="name"))
		with (
			patch.object(storage_bridge, "utc_today", return_value=frappe.utils.getdate("2026-06-01")),
			patch.object(TeamService, "get_usage", new=usage),
		):
			read()
		logs = frappe.get_all("Error Log", filters=region_logs, fields=["name", "method"])
		new = [log for log in logs if log.name not in before]
		frappe.db.delete("Error Log", {"name": ["in", [log.name for log in new]]})
		return [log.method for log in new]

	def test_a_bucket_that_cannot_be_read_does_not_stop_the_page(self):
		broken = self.broken_bucket("2")
		logs = self.new_region_logs(lambda: read_one_page([broken, self.bucket.name]))
		self.assertEqual([d.quantity for d in self.days()], [30])
		self.assertEqual(logs, [f"Storage usage: 1 bucket(s) not read in {CLUSTER}"])

	def read_whole_run(self, names: list[str], enqueue) -> None:
		frappe.db.set_value("Service", STORAGE_SERVICE, "central_reads", 1)
		with (
			patch.object(storage_bridge, "PAGE_SIZE", 1),
			patch.object(storage_bridge, "billed_buckets", return_value={CLUSTER: names}),
			patch("frappe.enqueue", side_effect=enqueue),
		):
			storage_bridge.read_storage_usage()

	def test_a_region_of_many_pages_is_read_in_one_job_per_page(self):
		pages = []
		names = [self.bucket.name, self.broken_bucket("2")]
		self.read_whole_run(names, lambda method, **kwargs: pages.append(kwargs["names"]))
		self.assertEqual(pages, [[name] for name in names])

	def test_a_run_logs_one_error_per_region_for_all_its_pages(self):
		from central.billing.tests.utils import run_enqueued_inline

		names = [self.broken_bucket("2"), self.bucket.name, self.broken_bucket("3")]
		logs = self.new_region_logs(lambda: self.read_whole_run(names, run_enqueued_inline))
		self.assertEqual([d.quantity for d in self.days()], [30])
		self.assertEqual(logs, [f"Storage usage: 2 bucket(s) not read in {CLUSTER}"])

	def test_a_page_that_fails_to_write_still_logs_its_region_once(self):
		from frappe.deferred_insert import save_to_db

		def crash():
			with (
				patch.object(storage_bridge, "write_days", side_effect=frappe.QueryDeadlockError),
				self.assertRaises(frappe.QueryDeadlockError),
			):
				read_one_page([self.bucket.name])
			save_to_db("Error Log")

		self.assertEqual(self.new_region_logs(crash), [f"Storage usage: 1 bucket(s) not read in {CLUSTER}"])
