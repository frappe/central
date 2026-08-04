# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Bulk re-issue: preview changes nothing, apply cancels and reissues, both audited."""

from unittest.mock import patch

import frappe

from central.billing.revenue import rerating
from central.billing.states import InvalidTransition
from central.billing.tests.utils import BillingTestCase, ensure_team

RESOURCE_TYPE = "Tokens"
PERIOD = ("2026-06-01", "2026-06-30")


class TestRerating(BillingTestCase):
	def setUp(self):
		self.team = ensure_team("team-rerating")

	def _invoice(self, status="Open", total=100.0, resource_type=RESOURCE_TYPE, team=None):
		# One live invoice per team per period is a DB-level invariant, so a test that
		# needs two invoices in one period needs two teams.
		return frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": team or self.team,
				"status": status,
				"period_start": PERIOD[0],
				"period_end": PERIOD[1],
				"currency": "USD",
				"subtotal": total,
				"total": total,
				"expected_collection": total,
				"items": [
					{
						"resource_type": resource_type,
						"quantity": 1,
						"rate": total,
						"amount": total,
						"unit": "Nos",
					}
				],
			}
		).insert(ignore_permissions=True)

	def test_only_invoices_carrying_the_resource_type_are_affected(self):
		wanted = self._invoice()
		other = self._invoice(resource_type="Storage", team=ensure_team("team-rerating-2"))

		affected = rerating.affected_invoices(RESOURCE_TYPE, *PERIOD)
		self.assertIn(wanted.name, affected)
		self.assertNotIn(other.name, affected)

	def test_a_paid_invoice_is_never_touched_by_a_reissue(self):
		paid = self._invoice(status="Paid")
		self.assertNotIn(paid.name, rerating.affected_invoices(RESOURCE_TYPE, *PERIOD))

	def test_preview_reports_the_delta_and_changes_nothing(self):
		invoice = self._invoice(total=100.0)
		with patch.object(rerating, "_rated_today", return_value=60.0):
			plan = rerating.preview(RESOURCE_TYPE, *PERIOD)

		row = next(r for r in plan["invoices"] if r["invoice"] == invoice.name)
		self.assertEqual(row["old_total"], 100.0)
		self.assertEqual(row["new_total"], 60.0)
		self.assertEqual(row["delta"], -40.0)
		self.assertEqual(frappe.db.get_value("Invoice", invoice.name, "status"), "Open")

	def test_apply_cancels_each_affected_invoice_and_records_the_run(self):
		invoice = self._invoice()
		with patch.object(rerating, "_rated_today", return_value=60.0), patch.object(
			rerating, "reissue_invoice", return_value="INV-NEW"
		) as reissue:
			run_name = rerating.apply(RESOURCE_TYPE, *PERIOD, reason="rate was wrong")

		reissue.assert_called_once()
		self.assertEqual(reissue.call_args.args[0], invoice.name)

		run = frappe.get_doc("Rerating Run", run_name)
		self.assertEqual(run.status, "Complete")
		self.assertEqual(run.reissued, 1)
		self.assertEqual(run.failed, 0)
		self.assertEqual(run.reason, "rate was wrong")
		self.assertIsNotNone(run.completed_at)

	def test_one_invoice_failing_does_not_stop_the_rest(self):
		self._invoice()
		self._invoice(team=ensure_team("team-rerating-2"))

		def flaky(invoice, **_kwargs):
			if not getattr(flaky, "called", False):
				flaky.called = True
				raise RuntimeError("nope")
			return "INV-NEW"

		with patch.object(rerating, "_rated_today", return_value=60.0), patch.object(
			rerating, "reissue_invoice", side_effect=flaky
		):
			run_name = rerating.apply(RESOURCE_TYPE, *PERIOD, reason="partial")

		run = frappe.get_doc("Rerating Run", run_name)
		self.assertEqual(run.reissued, 1)
		self.assertEqual(run.failed, 1)
		self.assertEqual(run.status, "Complete")

	def test_a_run_where_everything_failed_is_marked_failed(self):
		self._invoice()
		with patch.object(rerating, "_rated_today", return_value=60.0), patch.object(
			rerating, "reissue_invoice", side_effect=RuntimeError("nope")
		):
			run_name = rerating.apply(RESOURCE_TYPE, *PERIOD, reason="all broken")

		self.assertEqual(frappe.db.get_value("Rerating Run", run_name, "status"), "Failed")

	def test_a_closed_run_cannot_be_reopened(self):
		self._invoice()
		with patch.object(rerating, "_rated_today", return_value=60.0), patch.object(
			rerating, "reissue_invoice", return_value="INV-NEW"
		):
			run_name = rerating.apply(RESOURCE_TYPE, *PERIOD, reason="done")

		run = frappe.get_doc("Rerating Run", run_name)
		with self.assertRaises(InvalidTransition):
			run.finish("Running")

	def test_the_run_is_recorded_on_the_event_stream(self):
		self._invoice()
		with patch.object(rerating, "_rated_today", return_value=60.0), patch.object(
			rerating, "reissue_invoice", return_value="INV-NEW"
		):
			run_name = rerating.apply(RESOURCE_TYPE, *PERIOD, reason="audited")

		events = frappe.get_all(
			"Billing Event",
			filters={"subject_doctype": "Rerating Run", "subject": run_name},
			fields=["from_state", "to_state"],
		)
		self.assertEqual(events, [{"from_state": "Running", "to_state": "Complete"}])
