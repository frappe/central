# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central checks what a pushing service reports against its own reading, and notices silence."""

import datetime
from unittest.mock import MagicMock, patch

import frappe

from central.billing.revenue import grove_bridge, storage_bridge, usage_checks
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.services.doctype.service.service import AI_SERVICE, STORAGE_SERVICE
from central.services.doctype.team_service.team_service import TeamService

DAY = datetime.date(2026, 6, 19)
TODAY = datetime.date(2026, 6, 20)
NOW = datetime.datetime(2026, 6, 20, 8, 0)
BUCKET = "t-checks-bom-media"
TEAM = "team-usage-checks"
GB = 1_000_000_000


class TestUsageChecks(IntegrationTestCase):
	def setUp(self):
		for name in (STORAGE_SERVICE, AI_SERVICE):
			before = frappe.db.get_value(
				"Service", name, ["enabled", "central_reads", "last_report_at"], as_dict=True
			)
			self.addCleanup(frappe.db.set_value, "Service", name, before)
			frappe.db.set_value("Service", name, {"enabled": 1, "central_reads": 0, "last_report_at": None})
		self.enterContext(patch.object(usage_checks, "utc_today", return_value=TODAY))
		self.enterContext(patch("frappe.utils.now_datetime", return_value=NOW))
		frappe.db.delete("Team Service", {"external_id": BUCKET})
		self.bucket = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": TEAM,
				"add_on_service": STORAGE_SERVICE,
				"region": "ap-south-1",
				"bucket_name": BUCKET,
				"external_id": BUCKET,
				"status": "Active",
			}
		)
		self.bucket.db_insert()  # Skips before_insert, which would create the bucket in Cargo.
		self.addCleanup(frappe.db.delete, "Team Service", {"external_id": BUCKET})

	def stored_day(self, service, subject, quantity, dimension=""):
		frappe.get_doc(
			{
				"doctype": "Usage Day",
				"service": service,
				"meter": "bytes_stored" if service == STORAGE_SERVICE else "cost",
				"subject": subject,
				"dimension": dimension,
				"day": DAY,
				"aggregation": "Level" if service == STORAGE_SERVICE else "Sum",
				"quantity": quantity,
			}
		).db_insert()

	def sample(self, gb: float, day=DAY, names=None):
		with (
			patch.object(TeamService, "get_usage", return_value={"used_bytes": gb * GB}),
			patch.object(storage_bridge, "utc_today", return_value=day),
		):
			return usage_checks.sample_storage_page("ap-south-1", names or [self.bucket.name])

	def check(self, service=STORAGE_SERVICE):
		return frappe.get_all(
			"Usage Check",
			filters={"service": service},
			fields=["subject", "dimension", "read_value", "stored_value", "is_mismatch", "checked_at"],
			order_by="dimension asc, subject asc",
		)

	def test_a_stored_peak_below_centrals_sample_is_a_mismatch(self):
		self.sample(100)
		self.stored_day(STORAGE_SERVICE, BUCKET, 90)
		usage_checks.compare_storage(DAY)
		[check] = self.check()
		self.assertEqual((check.read_value, check.stored_value, check.is_mismatch), (100, 90, 1))
		[alert] = usage_checks.usage_mismatches()
		self.assertEqual(
			alert["detail"],
			f"storage {BUCKET} on 2026-06-19 (UTC): Central read 100 GB, the day holds 90 GB",
		)

	def test_a_peak_at_or_above_the_sample_passes(self):
		self.sample(100)
		self.stored_day(STORAGE_SERVICE, BUCKET, 99.5)
		usage_checks.compare_storage(DAY)
		self.assertEqual(self.check()[0].is_mismatch, 0)
		self.assertFalse(usage_checks.usage_mismatches())

	def test_each_bucket_keeps_its_own_peak_and_outcome(self):
		usage_checks._insert(
			[
				usage_checks._check(STORAGE_SERVICE, "bytes_stored", subject, "", DAY, 100, NOW)
				for subject in ("bucket-low", "bucket-ok", "bucket-missing")
			]
		)
		self.stored_day(STORAGE_SERVICE, "bucket-low", 80)
		self.stored_day(STORAGE_SERVICE, "bucket-ok", 120)
		self.assertEqual(usage_checks.compare_storage(DAY), 3)
		self.assertEqual(
			[(c.subject, c.stored_value, c.is_mismatch, bool(c.checked_at)) for c in self.check()],
			[("bucket-low", 80, 1, True), ("bucket-missing", 0, 0, True), ("bucket-ok", 120, 0, True)],
		)

	def test_a_missing_day_is_left_to_readiness(self):
		self.sample(100)
		usage_checks.compare_storage(DAY)
		[check] = self.check()
		self.assertEqual(check.is_mismatch, 0)
		self.assertTrue(check.checked_at)

	def test_a_second_sample_of_the_day_keeps_the_first(self):
		self.sample(100)
		self.sample(500)
		self.assertEqual([c.read_value for c in self.check()], [100])

	def test_a_bucket_that_fails_is_logged_and_the_page_goes_on(self):
		self.assertEqual(self.sample(10, names=["no-such-bucket", self.bucket.name]), 1)
		self.assertEqual([c.subject for c in self.check()], [BUCKET])

	def test_a_backup_bucket_is_sampled_with_the_bundled_reader(self):
		bucket = frappe._dict(external_id=BUCKET, team=TEAM, region="ap-south-1", included=50)
		client = MagicMock()
		client.get_usage.return_value = {"usage": {"used_bytes": 70 * GB}}
		with (
			patch.object(storage_bridge, "bundled_buckets", return_value={BUCKET: bucket}),
			patch.object(storage_bridge.ObjectStorageClient, "from_region", return_value=client),
			patch.object(storage_bridge, "utc_today", return_value=DAY),
		):
			usage_checks.sample_storage_page("ap-south-1", [BUCKET], bundled=True)
		self.assertEqual([(c.subject, c.read_value) for c in self.check()], [(BUCKET, 70)])

	def check_ai(self, models: dict):
		grove = [
			{"subject": TEAM, "dimension": model, "quantity": quantity} for model, quantity in models.items()
		]
		with (
			patch.object(
				usage_checks, "billed_subjects", return_value={TEAM: frappe._dict(external_id=TEAM)}
			),
			patch.object(grove_bridge.GroveClient, "from_settings"),
			patch.object(grove_bridge, "landing_rows", return_value=grove),
		):
			usage_checks.check_ai_page([TEAM], str(DAY))

	def test_ai_days_are_compared_per_model(self):
		self.stored_day(AI_SERVICE, TEAM, 1.25, dimension="model-a")
		self.stored_day(AI_SERVICE, TEAM, 3.0, dimension="model-b")
		self.check_ai({"model-a": 1.255, "model-b": 2.5})
		checks = self.check(AI_SERVICE)
		self.assertEqual([(c.dimension, c.is_mismatch) for c in checks], [("model-a", 0), ("model-b", 1)])

	def test_a_model_only_the_ledger_has_is_a_mismatch(self):
		self.stored_day(AI_SERVICE, TEAM, 2.0, dimension="model-gone")
		self.check_ai({})
		[check] = self.check(AI_SERVICE)
		self.assertEqual((check.read_value, check.stored_value, check.is_mismatch), (0, 2.0, 1))

	def test_a_team_grove_cannot_answer_for_is_not_checked(self):
		self.stored_day(AI_SERVICE, TEAM, 2.0, dimension="model-a")
		with (
			patch.object(
				usage_checks, "billed_subjects", return_value={TEAM: frappe._dict(external_id=TEAM)}
			),
			patch.object(grove_bridge.GroveClient, "from_settings"),
			patch.object(grove_bridge, "landing_rows", side_effect=RuntimeError("grove down")),
		):
			self.assertEqual(usage_checks.check_ai_page([TEAM], str(DAY)), 0)
		self.assertFalse(self.check(AI_SERVICE))

	def test_nothing_runs_while_central_reads_the_service(self):
		self.sample(100)
		self.stored_day(STORAGE_SERVICE, BUCKET, 90)
		usage_checks.compare_storage(DAY)
		self.sample(100, day=TODAY)
		frappe.db.set_value("Service", STORAGE_SERVICE, "central_reads", 1)
		frappe.db.set_value("Service", AI_SERVICE, "central_reads", 1)
		with patch("frappe.enqueue") as enqueue:
			self.assertEqual(usage_checks.sample_storage(), 0)
			self.assertEqual(usage_checks.check_ai(DAY), 0)
		enqueue.assert_not_called()
		self.assertEqual(usage_checks.compare_storage(TODAY), 0)
		self.assertFalse(frappe.db.get_value("Usage Check", {"day": TODAY}, "checked_at"))
		self.assertFalse(usage_checks.silent_services())
		self.assertFalse(usage_checks.usage_mismatches())

	def test_buckets_are_sampled_in_pages_by_region(self):
		names = [f"b{n}" for n in range(250)]
		with (
			patch.object(usage_checks, "billed_buckets", return_value={"ap-south-1": names[:125]}),
			patch.object(usage_checks, "bundled_buckets_by_region", return_value={"eu-west-1": names[125:]}),
			patch("frappe.enqueue") as enqueue,
		):
			self.assertEqual(usage_checks.sample_storage(), 250)
		pages = [(call.kwargs["bundled"], len(call.kwargs["names"])) for call in enqueue.call_args_list]
		self.assertEqual(sorted(pages), [(False, 25), (False, 100), (True, 25), (True, 100)])

	def test_a_service_silent_for_twice_its_cadence_raises_an_alert(self):
		frappe.db.set_value("Service", STORAGE_SERVICE, "last_report_at", NOW - datetime.timedelta(hours=3))
		frappe.db.set_value("Service", AI_SERVICE, "last_report_at", NOW - datetime.timedelta(minutes=90))
		[alert] = usage_checks.silent_services()
		self.assertEqual(alert["subject"], STORAGE_SERVICE)
		self.assertIn(f"({frappe.utils.get_system_timezone()})", alert["detail"])

	def test_a_service_that_never_reported_is_silent(self):
		alerts = {a["subject"]: a for a in usage_checks.silent_services()}
		self.assertIn(STORAGE_SERVICE, alerts)
		self.assertIn("No report", alerts[STORAGE_SERVICE]["detail"])

	def test_a_daily_service_has_two_days(self):
		frappe.db.set_value(
			"Service",
			STORAGE_SERVICE,
			{"expected_cadence": "Daily", "last_report_at": NOW - datetime.timedelta(hours=30)},
		)
		self.addCleanup(frappe.db.set_value, "Service", STORAGE_SERVICE, "expected_cadence", "Hourly")
		self.assertNotIn(STORAGE_SERVICE, [a["subject"] for a in usage_checks.silent_services()])

	def test_checks_older_than_seven_days_are_pruned(self):
		self.sample(10, day=TODAY - datetime.timedelta(days=8))
		self.sample(10, day=TODAY - datetime.timedelta(days=7))
		self.assertEqual(usage_checks.prune_checks(), 1)
		self.assertEqual(len(self.check()), 1)
