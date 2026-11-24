# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A server's backup bucket takes pushed lines only for the days its server billed."""

from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.revenue import report_subjects, service_reports
from central.billing.tests import test_bundled_buckets as base
from central.billing.tests.test_service_reports import signed
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, complete_billing_profile, give_team_a_card

SECRET = "storage-report-secret"
PAUSED_AT = "2026-06-02 12:00:00"


class TestPushedBackupBuckets(base.BundledServerFixture, IntegrationTestCase):
	def setUp(self):
		self.set_up_bundled_server()
		storage = frappe.get_doc("Service", "storage")
		before = (
			storage.enabled,
			storage.central_reads,
			storage.get_password("report_secret", raise_exception=False),
		)
		storage.enabled = 1
		# Cargo pushes storage, so Central stores what it sends.
		storage.central_reads = 0
		storage.report_secret = SECRET
		storage.save()
		self.addCleanup(self.restore_storage, before)

	def restore_storage(self, before):
		storage = frappe.get_doc("Service", "storage")
		storage.enabled, storage.central_reads = before[0], before[1]
		storage.report_secret = before[2] or ""
		storage.save()

	def send(self, days: list[str], gb: float = 100, today: str = "2026-06-30") -> dict:
		lines = [
			{"subject": self.bucket, "meter": "bytes_stored", "day": day, "value": gb * base.GB}
			for day in days
		]
		raw, signature = signed({"as_of": "2026-06-03T06:00:00Z", "lines": lines}, SECRET)
		with patch.object(report_subjects, "utc_today", return_value=frappe.utils.getdate(today)):
			return service_reports.accept_report("storage", signature, raw)

	def stored_days(self) -> list:
		return frappe.get_all(
			"Usage Day",
			filters={"subject": self.bucket},
			fields=["day", "quantity", "included", "subscription"],
			order_by="day asc",
		)

	def team_bucket_of_the_same_name(self) -> str:
		"""A team's own bucket that shares the backup bucket's name, and its subscription."""
		complete_billing_profile(base.TEAM)
		give_team_a_card(base.TEAM)
		subscription = provision_service_subscription(
			base.TEAM, base.STORAGE_PLAN, cluster=base.CLUSTER, start_date="2026-06-01"
		)["subscription"]
		frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": base.TEAM,
				"add_on_service": "storage",
				"region": base.CLUSTER,
				"bucket_name": self.bucket,
				"external_id": self.bucket,
				"status": "Active",
				"subscription": subscription,
			}
		).db_insert()  # Skips before_insert, which would create the bucket in Cargo.
		self.addCleanup(frappe.db.delete, "Team Service", {"team": base.TEAM})
		return subscription

	def subjects_on(self, days: set[str]) -> dict:
		with patch.object(report_subjects, "utc_today", return_value=frappe.utils.getdate("2026-06-04")):
			return report_subjects.subjects_by_day("storage", [self.bucket], days)

	def test_a_billed_servers_bucket_is_taken_with_its_days_bundle(self):
		answer = self.send(["2026-06-01"])

		self.assertEqual(answer, {"accepted": 1, "rejected": []})
		[day] = self.stored_days()
		self.assertEqual((day.quantity, day.included, day.subscription), (100, 40, self.subscription))

	def test_each_day_of_a_report_is_resolved_on_its_own(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)

		answer = self.send(["2026-06-02", "2026-06-03"])

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual([r["day"] for r in answer["rejected"]], ["2026-06-03"])
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")
		self.assertEqual([str(day.day) for day in self.stored_days()], ["2026-06-02"])

	def test_a_paused_servers_recent_day_does_not_keep_its_bucket_billing(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)
		self.send(["2026-06-02"], today="2026-06-03")

		answer = self.send(["2026-06-03"], today="2026-06-03")

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")

	def test_a_name_billed_on_one_day_is_a_deleted_subject_on_another(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)
		own = self.team_bucket_of_the_same_name()
		self.send(["2026-06-03"], today="2026-06-04")
		frappe.db.delete("Team Service", {"team": base.TEAM})

		together = self.subjects_on({"2026-06-02", "2026-06-03"})
		alone = {day: self.subjects_on({day})[day] for day in together}
		answer = self.send(["2026-06-02", "2026-06-03"], today="2026-06-04")

		self.assertEqual(together, alone)
		self.assertEqual(together["2026-06-02"][self.bucket].subscription, self.subscription)
		self.assertEqual(together["2026-06-03"][self.bucket].subscription, own)
		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		subscriptions = [(str(day.day), day.subscription) for day in self.stored_days()]
		self.assertEqual(subscriptions, [("2026-06-02", self.subscription), ("2026-06-03", own)])

	def test_a_paused_servers_bucket_stays_unknown_beside_a_billed_day(self):
		add_segment(self.subscription, "Paused", 0, PAUSED_AT, plan=base.VM_PLAN)
		self.send(["2026-06-02"], today="2026-06-03")

		answer = self.send(["2026-06-02", "2026-06-03"], today="2026-06-03")

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual([r["day"] for r in answer["rejected"]], ["2026-06-03"])
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")
