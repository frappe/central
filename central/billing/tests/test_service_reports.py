# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A service pushes each day's value so far, signed with its own secret, only for its subjects."""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.revenue import report_subjects, service_reports, usage_ledger
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	complete_billing_profile,
	ensure_team,
	give_team_a_card,
	make_plan,
)

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


class TestServiceReports(IntegrationTestCase):
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
			}
		).db_insert()  # Skips before_insert, which would create the bucket in Cargo.

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

	def restore_storage(self, before):
		storage = frappe.get_doc("Service", "storage")
		storage.enabled, storage.central_reads = before[0], before[1]
		storage.report_secret = before[2] or ""
		storage.save()

	def send(self, lines, as_of="2026-06-20T06:30:00Z", secret=SECRET):
		raw, signature = signed({"as_of": as_of, "lines": lines}, secret)
		return service_reports.accept_report("storage", signature, raw)

	def days(self):
		return frappe.get_all(
			"Usage Day", filters={"team": TEAM}, fields=["day", "quantity"], order_by="day asc", as_list=True
		)

	def test_a_signed_report_stores_each_day(self):
		answer = self.send([line("2026-06-19", 10), line("2026-06-20", 12)])
		self.assertEqual(answer, {"accepted": 2, "rejected": []})
		self.assertEqual([q for _d, q in self.days()], [10, 12])

	def test_a_day_written_at_the_same_time_is_rejected_to_be_sent_again(self):
		self.send([line("2026-06-20", 10)])
		with patch.object(usage_ledger, "_existing_days", return_value={}):
			answer = self.send([line("2026-06-19", 8), line("2026-06-20", 12)])
		self.assertEqual(answer["accepted"], 1)
		self.assertEqual(
			answer["rejected"],
			[
				{
					"subject": BUCKET,
					"meter": "bytes_stored",
					"day": "2026-06-20",
					"dimension": "",
					"reason": "the day changed at the same time; send it again",
					"retry": True,
				}
			],
		)
		self.assertEqual([q for _d, q in self.days()], [8, 10])

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

	def test_a_deleted_buckets_last_day_bills_the_subscription_it_billed(self):
		self.send([line("2026-06-19", 10)])
		billed = frappe.db.get_value("Usage Day", {"subject": BUCKET}, "subscription")
		frappe.db.delete("Team Service", {"team": TEAM})

		answer = self.send_on("2026-06-21", [line("2026-06-20", 12)])

		self.assertEqual(answer, {"accepted": 1, "rejected": []})
		self.assertEqual(
			frappe.db.get_value("Usage Day", {"subject": BUCKET, "day": "2026-06-20"}, "subscription"),
			billed,
		)

	def test_a_bucket_deleted_more_than_two_days_ago_is_an_unknown_subject(self):
		self.send([line("2026-06-17", 10)])
		frappe.db.delete("Team Service", {"team": TEAM})

		answer = self.send_on("2026-06-21", [line("2026-06-20", 12)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")
		self.assertTrue(answer["rejected"][0]["retry"])

	def copy_usage_day(self, day: str, subscription: str | None = None):
		"""A copy of the bucket's only Usage Day, moved to `day` and, if given, `subscription`."""
		copy = frappe.copy_doc(frappe.get_doc("Usage Day", {"subject": BUCKET}))
		copy.day = day
		copy.subscription = subscription or copy.subscription
		copy.db_insert()  # Skips validation, as a row written by an older Central would.

	def server_subscription(self) -> str:
		"""A copy of the bucket's subscription that bills a server instead."""
		billed = frappe.db.get_value("Usage Day", {"subject": BUCKET}, "subscription")
		server = frappe.copy_doc(frappe.get_doc("Subscription", billed))
		server.server_id = "service-reports-server"
		server.db_insert()  # Skips validation; only server_id matters here.
		return server.name

	def test_a_deleted_subject_whose_latest_day_is_on_a_server_is_an_unknown_subject(self):
		self.send([line("2026-06-19", 10)])
		self.copy_usage_day("2026-06-20", self.server_subscription())
		frappe.db.delete("Team Service", {"team": TEAM})

		answer = self.send_on("2026-06-21", [line("2026-06-20", 12)])

		self.assertEqual(answer["accepted"], 0)
		self.assertEqual(answer["rejected"][0]["reason"], "unknown subject")

	def test_a_deleted_subject_whose_latest_day_is_after_today_is_an_unknown_subject(self):
		self.send([line("2026-06-19", 10)])
		self.copy_usage_day("2026-06-25")
		frappe.db.delete("Team Service", {"team": TEAM})

		answer = self.send_on("2026-06-21", [line("2026-06-20", 12)])

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
