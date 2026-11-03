# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Each billing data patch repairs the state it was written for."""

import frappe
from frappe.utils import add_days, getdate

from central.billing import settings
from central.billing.doctype.invoice.invoice import period_key_for
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_atlas_instance, ensure_team
from central.patches.v0_0 import (
	mark_waived_invoices_as_not_synced,
	merge_invoice_draft_and_open_into_outstanding,
	move_internal_flag_to_billing_profile,
	repoint_billing_records_to_renamed_region,
	start_billing_run_outcomes_and_minimum_invoices,
)

TEAM = "team-data-patch"
OTHER_TEAM = "team-data-patch-other"


def _insert_invoice(status: str, period_end: str, team: str = TEAM, **fields) -> str:
	period_start = frappe.utils.get_first_day(period_end)
	doc = frappe.get_doc(
		{
			"doctype": "Invoice",
			"team": team,
			"invoice_type": "Billable",
			"status": status,
			"period_start": period_start,
			"period_end": period_end,
			"period_key": period_key_for(team, period_start, getdate(period_end)),
			"currency": "INR",
			**fields,
		}
	)
	doc.db_insert()
	return doc.name


def _invoice(name: str):
	return frappe.db.get_value("Invoice", name, ["status", "due_date", "erpnext_sync_status"], as_dict=True)


class TestBillingDataPatches(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)

	def test_records_of_a_renamed_region_point_at_its_new_name(self):
		ensure_atlas_instance("bom")
		subscription = frappe.get_doc({"doctype": "Subscription", "team": TEAM, "cluster": "mumbai"})
		subscription.db_insert()
		rollup = frappe.get_doc({"doctype": "Usage Rollup", "team": TEAM, "cluster": "mumbai"})
		rollup.db_insert()

		repoint_billing_records_to_renamed_region.execute()

		self.assertEqual(frappe.db.get_value("Subscription", subscription.name, "cluster"), "bom")
		self.assertEqual(frappe.db.get_value("Usage Rollup", rollup.name, "cluster"), "bom")

	def test_draft_and_open_become_outstanding_and_open_keeps_a_due_date(self):
		draft = _insert_invoice("Draft", "2026-05-31", due_date="2026-06-10")
		opened = _insert_invoice("Open", "2026-04-30")
		frappe.db.set_value("Invoice", opened, "modified", "2026-05-01 10:00:00", update_modified=False)

		merge_invoice_draft_and_open_into_outstanding.execute()

		self.assertEqual((_invoice(draft).status, _invoice(draft).due_date), ("Outstanding", None))
		due = add_days(getdate("2026-05-01"), settings.invoice_due_days())
		self.assertEqual((_invoice(opened).status, _invoice(opened).due_date), ("Outstanding", due))

	def test_the_internal_flag_moves_to_the_billing_profile(self):
		ensure_team(OTHER_TEAM)
		complete_billing_profile(TEAM)
		tax = frappe.qb.DocType("Tax Profile")
		for team, reason in ((TEAM, "Our own servers"), (OTHER_TEAM, None)):
			frappe.db.delete("Tax Profile", {"team": team})
			frappe.get_doc({"doctype": "Tax Profile", "team": team}).db_insert()
			frappe.qb.update(tax).set(tax.is_internal, 1).set(tax.internal_reason, reason).where(
				tax.team == team
			).run()

		move_internal_flag_to_billing_profile.execute()

		profiles = frappe.get_all(
			"Billing Profile",
			filters={"team": ["in", [TEAM, OTHER_TEAM]]},
			fields=["team", "is_internal", "internal_reason"],
			as_list=True,
		)
		self.assertEqual(
			sorted(profiles),
			[(TEAM, 1, "Our own servers"), (OTHER_TEAM, 1, "Marked internal on the Tax Profile")],
		)

	def test_a_waived_invoice_is_not_waiting_for_accounting(self):
		waived = _insert_invoice("Waived", "2026-05-31", erpnext_sync_status="Pending")
		paid = _insert_invoice("Paid", "2026-04-30", erpnext_sync_status="Pending")

		mark_waived_invoices_as_not_synced.execute()

		self.assertEqual(_invoice(waived).erpnext_sync_status, "Not Required")
		self.assertEqual(_invoice(paid).erpnext_sync_status, "Pending")


class TestStartBillingRunOutcomes(IntegrationTestCase):
	def setUp(self):
		for team in (TEAM, OTHER_TEAM):
			ensure_team(team)

	def _run_team(self, team: str, period_end: str):
		return frappe.db.get_value(
			"Billing Run Team", {"team": team, "period_end": period_end}, ["outcome", "reason"], as_dict=True
		)

	def test_old_events_get_a_flow_and_an_outcome(self):
		event = frappe.get_doc(
			{
				"doctype": "Billing Event",
				"team": TEAM,
				"event_type": "Customer Sync Failed",
				"subject_doctype": "Billing Profile",
				"subject": TEAM,
			}
		)
		event.db_insert()

		start_billing_run_outcomes_and_minimum_invoices.execute()

		row = frappe.db.get_value("Billing Event", event.name, ["category", "outcome"], as_dict=True)
		self.assertEqual((row.category, row.outcome), ("Billing Profile", "Failed"))

	def test_a_billed_team_with_no_tax_profile_gets_one(self):
		complete_billing_profile(TEAM)
		frappe.db.delete("Tax Profile", {"team": TEAM})

		start_billing_run_outcomes_and_minimum_invoices.execute()

		self.assertTrue(frappe.db.exists("Tax Profile", TEAM))

	def test_a_team_the_last_run_missed_is_queued_for_the_retry(self):
		frappe.get_doc(
			{"doctype": "Billing Run", "name": "2026-05-31", "period_end": "2026-05-31", "drafted": 1}
		).db_insert()
		frappe.get_doc({"doctype": "Subscription", "team": TEAM, "enabled": 1}).db_insert()
		frappe.get_doc({"doctype": "Subscription", "team": OTHER_TEAM, "enabled": 1}).db_insert()
		_insert_invoice("Paid", "2026-05-31", team=OTHER_TEAM, due_date="2026-06-10")

		start_billing_run_outcomes_and_minimum_invoices.execute()

		self.assertEqual(self._run_team(TEAM, "2026-05-31").outcome, "Failed")
		self.assertIsNone(self._run_team(OTHER_TEAM, "2026-05-31"))

	def test_an_unissued_invoice_below_the_minimum_is_written_off(self):
		small = _insert_invoice("Outstanding", "2026-04-30", total=10)
		issued = _insert_invoice("Outstanding", "2026-03-31", total=10, due_date="2026-04-10")

		start_billing_run_outcomes_and_minimum_invoices.execute()

		self.assertEqual(_invoice(small).status, "Cancelled")
		self.assertEqual(_invoice(issued).status, "Outstanding")
		outcome = self._run_team(TEAM, "2026-04-30")
		self.assertEqual(outcome.outcome, "Below Minimum")
		self.assertIn("written off", outcome.reason)
