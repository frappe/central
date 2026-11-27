# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A service pushes each day's value so far, signed with its own secret, only for its subjects."""

import base64
import datetime
import hashlib
import hmac
import json
from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.revenue import report_subjects, service_reports, usage_ledger, usage_month, usage_reports
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	complete_billing_profile,
	ensure_team,
	give_team_a_card,
	make_plan,
	refused_lock,
	usage_days,
)
from central.services.doctype.team_service import team_service

TEAM = "team-service-reports"
CLUSTER = "ap-south-1"
PLAN = "service-reports-storage-plan"
BUCKET = "t-reports-ap-south-1-media"
SECRET = "storage-report-secret"
GB = 1_000_000_000
NOW = "2026-06-20 12:00:00"


def signed(body: dict, secret: str = SECRET) -> tuple[bytes, str]:
	raw = json.dumps(body).encode()
	return raw, base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()


def line(day: str, gb: float, subject: str = BUCKET) -> dict:
	return {"subject": subject, "meter": "bytes_stored", "day": day, "value": gb * GB}


class ServiceReportsCase(IntegrationTestCase):
	"""A storage service that pushes its reports, with one team bucket billed from June 1."""

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
		self.make_bucket()

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
		self.enterContext(patch("frappe.utils.now_datetime", return_value=frappe.utils.get_datetime(NOW)))

	def make_bucket(self, created: str = "2026-06-01 00:00:00") -> None:
		"""The team's bucket, created at `created` and billed on a storage subscription from June 1."""
		subscription = provision_service_subscription(TEAM, PLAN, cluster=CLUSTER, start_date="2026-06-01")
		frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": TEAM,
				"add_on_service": "storage",
				"region": CLUSTER,
				"bucket_name": BUCKET,
				"external_id": BUCKET,
				"status": "Active",
				"subscription": subscription["subscription"],
				"creation": created,
			}
		).db_insert()  # Skips before_insert, which would create the bucket in Cargo.

	def restore_storage(self, before):
		storage = frappe.get_doc("Service", "storage")
		storage.enabled, storage.central_reads = before[0], before[1]
		storage.report_secret = before[2] or ""
		storage.save()

	def send(self, lines, as_of="2026-06-20T06:30:00Z", secret=SECRET):
		raw, signature = signed({"as_of": as_of, "lines": lines}, secret)
		return service_reports.accept_report("storage", signature, raw)

	def days(self):
		return [(day.day, day.quantity) for day in usage_days(team=TEAM)]


class TestServiceReports(ServiceReportsCase):
	def test_a_signed_report_stores_each_day(self):
		answer = self.send([line("2026-06-19", 10), line("2026-06-20", 12)])
		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		self.assertEqual([q for _d, q in self.days()], [10, 12])

	def test_a_month_written_at_the_same_time_is_rejected_to_be_sent_again(self):
		self.send([line("2026-06-20", 10)])
		reports = set(frappe.get_all("Usage Report", pluck="name"))
		# Under snapshot isolation a month row another worker changed meanwhile refuses the lock,
		# and the whole transaction is rolled back, the new month row of the 19th with it.
		with refused_lock():
			answer = self.send([line("2026-06-19", 8), line("2026-06-20", 12)])
		self.assertEqual(answer["accepted"], 0)
		# The report is still kept, with its body, as evidence of what was refused.
		[report] = set(frappe.get_all("Usage Report", pluck="name")) - reports
		self.assertEqual(
			frappe.db.get_value("Usage Report", report, ["accepted_count", "rejected_count"]), (0, 2)
		)
		self.assertTrue(usage_reports.is_intact(report))
		self.assertEqual(
			[(r["day"], r["reason"], r["retry"]) for r in answer["rejected"]],
			[
				("2026-06-19", "the day changed at the same time; send it again", True),
				("2026-06-20", "the day changed at the same time; send it again", True),
			],
		)
		self.assertEqual([q for _d, q in self.days()], [10])

	def test_each_stored_day_names_the_report_that_set_it(self):
		self.send([line("2026-06-20", 10)])
		[day] = usage_days(team=TEAM)
		self.assertEqual(day.source, "Pushed")
		self.assertEqual(frappe.db.get_value("Usage Report", day.report, "kind"), "Pushed")

	def test_a_wrong_signature_is_refused_whole(self):
		with self.assertRaises(frappe.PermissionError):
			self.send([line("2026-06-20", 10)], secret="not-the-secret")
		self.assertFalse(self.days())

	def test_an_unknown_subject_is_rejected_and_the_rest_stored(self):
		answer = self.send([line("2026-06-20", 10), line("2026-06-20", 5, subject="someone-elses-bucket")])
		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(
			answer["rejected"],
			[
				{
					"subject": "someone-elses-bucket",
					"meter": "bytes_stored",
					"day": "2026-06-20",
					"dimension": "",
					"reason": "unknown subject",
					"retry": True,
				}
			],
		)

	def test_a_day_in_the_future_is_rejected(self):
		answer = self.send([line("2999-01-01", 10)])
		self.assertEqual(answer["rejected"][0]["reason"], "day is in the future")
		self.assertTrue(answer["rejected"][0]["retry"])

	def test_a_report_sent_again_changes_nothing(self):
		self.send([line("2026-06-20", 10)])
		self.send([line("2026-06-20", 10)])
		self.assertEqual(len(self.days()), 1)

	def test_an_outbox_catching_up_fills_every_missed_day(self):
		self.send([line("2026-06-15", 10)])
		# Central was down from the 16th; the next report carries every unconfirmed day.
		self.send([line(f"2026-06-{day}", 10 + day) for day in range(16, 21)])
		self.assertEqual(len(self.days()), 6)

	def test_a_lower_reading_never_lowers_the_days_peak(self):
		self.send([line("2026-06-20", 30)], as_of="2026-06-20T05:30:00Z")
		self.send([line("2026-06-20", 5)], as_of="2026-06-20T06:00:00Z")
		self.assertEqual(self.days()[0][1], 30)

	def test_a_time_with_no_zone_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.send([line("2026-06-20", 10)], as_of="2026-06-20T06:30:00")

	def test_a_malformed_line_is_rejected_alone(self):
		good = line("2026-06-20", 10)
		bad = [
			{**good, "subject": ["a-list"]},
			{**good, "subject": {"a": "dict"}},
			{**good, "value": -1},
			{**good, "value": 1e300},
			{**good, "value": 10**19},
			{**good, "amount": 1e300},
			{**good, "amount": "12"},
			{**good, "currency": ["INR"]},
			{**good, "meter": ["bytes_stored"]},
		]
		answer = self.send([*bad, good])
		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(len(answer["rejected"]), len(bad))
		self.assertEqual([refusal["retry"] for refusal in answer["rejected"]], [False] * len(bad))
		self.assertEqual([q for _d, q in self.days()], [10])

	def test_a_refused_line_names_itself_even_when_malformed(self):
		answer = self.send(
			[{"subject": ["a-list"], "meter": 7, "day": "2026-06-20", "dimension": 5, "value": 1}]
		)
		self.assertEqual(
			{key: answer["rejected"][0][key] for key in ("subject", "meter", "day", "dimension", "retry")},
			{"subject": None, "meter": None, "day": "2026-06-20", "dimension": "", "retry": False},
		)

	def test_a_signed_report_records_when_the_service_last_reported(self):
		self.send([line("2026-06-20", 5, subject="someone-elses-bucket")])
		seen = frappe.db.get_value(
			"Service", "storage", ["last_report_at", "last_report_as_of"], as_dict=True
		)
		self.assertEqual(seen.last_report_at, frappe.utils.get_datetime(NOW))
		self.assertTrue(seen.last_report_as_of)

	def test_a_wrong_signature_records_nothing(self):
		before = frappe.db.get_value("Service", "storage", "last_report_at")
		with self.assertRaises(frappe.PermissionError):
			self.send([line("2026-06-20", 10)], secret="not-the-secret")
		self.assertEqual(frappe.db.get_value("Service", "storage", "last_report_at"), before)

	def send_on(self, today: str, lines):
		with patch.object(report_subjects, "utc_today", return_value=frappe.utils.getdate(today)):
			return self.send(lines)

	def delete_bucket(self, at: str = NOW) -> str:
		"""Delete the team's bucket at `at` as a team would; returns the subscription it billed."""
		name = frappe.db.get_value("Team Service", {"team": TEAM}, "name")
		billed = frappe.db.get_value("Team Service", name, "subscription")
		with (
			patch.object(team_service, "ObjectStorageClient"),
			patch("frappe.utils.now_datetime", return_value=frappe.utils.get_datetime(at)),
		):
			frappe.delete_doc("Team Service", name, ignore_permissions=True)
		return billed

	def billed_on(self, day: str) -> str | None:
		found = usage_days(subject=BUCKET, day=day)
		return found[0].subscription if found else None

	def test_a_bucket_deleted_today_bills_today_and_a_backlog_on_its_subscription(self):
		billed = self.delete_bucket()

		answer = self.send_on("2026-06-20", [line("2026-06-18", 8), line("2026-06-20", 12)])

		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		self.assertEqual((self.billed_on("2026-06-18"), self.billed_on("2026-06-20")), (billed, billed))

	def test_a_day_after_the_bucket_was_deleted_is_an_unknown_subject(self):
		self.delete_bucket("2026-06-19 12:00:00")

		answer = self.send_on("2026-06-20", [line("2026-06-19", 8), line("2026-06-20", 12)])

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual([r["day"] for r in answer["rejected"]], ["2026-06-20"])
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")
		self.assertTrue(answer["rejected"][0]["retry"])

	def test_a_bucket_deleted_three_days_ago_is_an_unknown_subject(self):
		self.delete_bucket("2026-06-17 12:00:00")

		answer = self.send_on("2026-06-20", [line("2026-06-17", 12)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")
		self.assertTrue(answer["rejected"][0]["retry"])

	def test_accepted_lines_for_a_deleted_bucket_do_not_extend_its_window(self):
		self.delete_bucket("2026-06-18 12:00:00")
		self.assertEqual(self.send_on("2026-06-20", [line("2026-06-18", 12)])["accepted"], 1)
		# A later day stored for the name, as an estimate or a stray write might leave one.
		[stored] = usage_days(subject=BUCKET)
		usage_month.write_lines([{**stored, "day": "2026-06-20"}], None, "Estimated")

		answer = self.send_on("2026-06-21", [line("2026-06-18", 13)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")

	def test_a_reused_name_bills_the_deletion_day_on_the_later_bucket(self):
		self.delete_bucket("2026-06-18 12:00:00")
		self.make_bucket("2026-06-18 13:00:00")
		later = self.delete_bucket()

		answer = self.send_on("2026-06-20", [line("2026-06-20", 12)])

		self.assertEqual(answer, {"accepted": 1, "rejected": []})
		self.assertEqual(self.billed_on("2026-06-20"), later)

	def test_a_reused_name_bills_each_day_on_the_bucket_alive_most_recently(self):
		first = self.delete_bucket("2026-06-18 12:00:00")
		self.make_bucket("2026-06-18 13:00:00")
		second = self.delete_bucket()
		self.assertNotEqual(first, second)

		days = ["2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20", "2026-06-21"]
		answer = self.send_on("2026-06-20", [line(day, 12) for day in days])

		self.assertEqual(answer["accepted"], 4)
		self.assertEqual(
			[(r["day"], r["reason"]) for r in answer["rejected"]], [("2026-06-21", "unknown subject")]
		)
		# Both buckets held the name on the 18th; Cargo's one peak goes on the later one.
		self.assertEqual([self.billed_on(day) for day in days[:4]], [first, second, second, second])

	def test_a_day_two_deletions_cover_bills_the_later_one(self):
		self.delete_bucket("2026-06-19 08:00:00")
		self.make_bucket("2026-06-19 09:00:00")
		later = self.delete_bucket("2026-06-19 15:00:00")

		answer = self.send_on("2026-06-20", [line("2026-06-19", 12)])

		self.assertEqual(answer, {"accepted": 1, "rejected": []})
		self.assertEqual(self.billed_on("2026-06-19"), later)

	def test_a_bucket_made_again_on_its_deletion_day_bills_that_day_on_the_live_bucket(self):
		deleted = self.delete_bucket("2026-06-20 08:00:00")
		self.make_bucket("2026-06-20 09:00:00")
		live = frappe.db.get_value("Team Service", {"team": TEAM}, "subscription")
		self.assertNotEqual(deleted, live)

		answer = self.send_on("2026-06-20", [line("2026-06-19", 8), line("2026-06-20", 12)])

		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		# The old team is never charged for the new bucket's data on the day they shared.
		self.assertEqual((self.billed_on("2026-06-19"), self.billed_on("2026-06-20")), (deleted, live))

	def test_a_name_made_again_today_leaves_earlier_days_on_the_deleted_bucket(self):
		deleted = self.delete_bucket("2026-06-19 12:00:00")
		self.make_bucket("2026-06-20 09:00:00")
		current = frappe.db.get_value("Team Service", {"team": TEAM}, "subscription")
		self.assertNotEqual(deleted, current)

		answer = self.send_on("2026-06-20", [line("2026-06-19", 8), line("2026-06-20", 12)])

		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		self.assertEqual((self.billed_on("2026-06-19"), self.billed_on("2026-06-20")), (deleted, current))

	def test_a_day_between_two_buckets_of_one_name_is_an_unknown_subject(self):
		# Deleted Monday, made again Wednesday, deleted Thursday: no bucket held the name on Tuesday.
		self.delete_bucket("2026-06-15 12:00:00")
		self.make_bucket("2026-06-17 09:00:00")
		thursday = self.delete_bucket("2026-06-18 12:00:00")

		answer = self.send_on("2026-06-18", [line("2026-06-16", 8), line("2026-06-18", 12)])

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(
			[(r["day"], r["reason"]) for r in answer["rejected"]], [("2026-06-16", "unknown subject")]
		)
		self.assertEqual(self.billed_on("2026-06-18"), thursday)

	def test_a_backlog_day_before_the_bucket_was_created_is_an_unknown_subject(self):
		frappe.db.set_value(
			"Team Service", {"team": TEAM}, "creation", "2026-06-19 09:00:00", update_modified=False
		)
		billed = self.delete_bucket()

		answer = self.send_on("2026-06-20", [line("2026-06-18", 8), line("2026-06-19", 12)])

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(
			[(r["day"], r["reason"]) for r in answer["rejected"]], [("2026-06-18", "unknown subject")]
		)
		self.assertEqual(self.billed_on("2026-06-19"), billed)

	def test_a_deletion_late_in_the_system_day_bills_up_to_its_utc_day(self):
		# 03:00 in Asia/Kolkata is 21:30 UTC the day before; pinned so the test holds on any site zone.
		self.enterContext(patch("frappe.utils.data.get_system_timezone", return_value="Asia/Kolkata"))
		billed = self.delete_bucket("2026-06-20 03:00:00")

		answer = self.send_on("2026-06-20", [line("2026-06-19", 8), line("2026-06-20", 12)])

		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(
			[(r["day"], r["reason"]) for r in answer["rejected"]], [("2026-06-20", "unknown subject")]
		)
		self.assertEqual(self.billed_on("2026-06-19"), billed)

	def test_a_deletion_just_before_the_window_is_an_unknown_subject(self):
		since = usage_ledger.utc_day_start("2026-06-18")
		self.delete_bucket(str(since - datetime.timedelta(seconds=1)))

		answer = self.send_on("2026-06-20", [line("2026-06-17", 8)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")

	def test_nothing_is_stored_while_central_still_reads_the_service(self):
		frappe.db.set_value("Service", "storage", "central_reads", 1)

		answer = self.send([line("2026-06-19", 10), line("2026-06-20", 12)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual([r["day"] for r in answer["rejected"]], ["2026-06-19", "2026-06-20"])
		self.assertTrue(all(r["retry"] for r in answer["rejected"]))
		self.assertIn("Central still reads this service", answer["rejected"][0]["reason"])
		self.assertFalse(self.days())

	def test_nothing_is_stored_when_central_reads_is_switched_on_after_verification(self):
		verify = service_reports.verified_service

		def switch_on_after_verifying(*args):
			service = verify(*args)
			frappe.db.set_value("Service", "storage", "central_reads", 1)
			return service

		with (
			patch.object(service_reports, "verified_service", side_effect=switch_on_after_verifying),
			patch.object(frappe.db, "get_value", wraps=frappe.db.get_value) as get_value,
		):
			answer = self.send([line("2026-06-19", 10)])

		self.assertEqual(answer["accepted"], 0)
		self.assertFalse(self.days())
		get_value.assert_any_call("Service", "storage", "central_reads", for_update=True)

	def test_a_report_refused_while_central_reads_still_shows_the_service_alive(self):
		frappe.db.set_value("Service", "storage", "central_reads", 1)

		self.send([line("2026-06-20", 12)])

		self.assertEqual(
			frappe.db.get_value("Service", "storage", "last_report_at"), frappe.utils.get_datetime(NOW)
		)
