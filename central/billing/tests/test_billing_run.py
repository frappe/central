# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The per-period Billing Run row tracks the run without ever being its own truth."""

import frappe

from central.billing.doctype.billing_run.billing_run import snapshot
from central.billing.states import InvalidTransition
from central.billing.tests.utils import BillingTestCase

PERIOD = {
	"period_start": "2026-06-01",
	"period_end": "2026-06-30",
	"teams": 10,
	"drafted": 8,
	"pending_draft": 2,
	"collected": 5,
	"pending_collection": 3,
	"failures": 1,
	"by_status": {"Draft": 3, "Paid": 5},
}


class TestBillingRun(BillingTestCase):
	def test_first_snapshot_creates_the_period_row(self):
		name = snapshot(PERIOD)
		doc = frappe.get_doc("Billing Run", name)
		self.assertEqual(doc.name, "2026-06-30")
		self.assertEqual(doc.status, "Drafting")
		self.assertEqual(doc.drafted, 8)
		self.assertEqual(doc.pending_collection, 3)
		self.assertIsNotNone(doc.started_at)

	def test_a_later_snapshot_updates_the_same_row(self):
		snapshot(PERIOD)
		snapshot({**PERIOD, "collected": 8, "pending_collection": 0})

		self.assertEqual(frappe.db.count("Billing Run", {"period_end": PERIOD["period_end"]}), 1)
		doc = frappe.get_doc("Billing Run", "2026-06-30")
		self.assertEqual(doc.collected, 8)
		self.assertEqual(doc.pending_collection, 0)

	def test_completing_stamps_the_finish_time_once(self):
		snapshot(PERIOD, "Collecting")
		snapshot({**PERIOD, "pending_collection": 0}, "Complete")
		finished = frappe.db.get_value("Billing Run", "2026-06-30", "completed_at")
		self.assertIsNotNone(finished)

		snapshot({**PERIOD, "pending_collection": 0}, "Complete")
		self.assertEqual(frappe.db.get_value("Billing Run", "2026-06-30", "completed_at"), finished)

	def test_a_late_draft_may_reopen_a_completed_period(self):
		snapshot(PERIOD, "Collecting")
		snapshot({**PERIOD, "pending_collection": 0}, "Complete")
		snapshot({**PERIOD, "pending_collection": 1}, "Collecting")
		self.assertEqual(frappe.db.get_value("Billing Run", "2026-06-30", "status"), "Collecting")

	def test_drafting_cannot_jump_straight_to_complete(self):
		snapshot(PERIOD)
		with self.assertRaises(InvalidTransition):
			snapshot(PERIOD, "Complete")

	def test_every_move_is_recorded_on_the_event_stream(self):
		snapshot(PERIOD, "Collecting")
		events = frappe.get_all(
			"Billing Event",
			filters={"subject_doctype": "Billing Run", "subject": "2026-06-30"},
			fields=["from_state", "to_state"],
		)
		self.assertEqual(events, [{"from_state": "Drafting", "to_state": "Collecting"}])
