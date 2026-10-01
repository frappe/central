# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A billable draft waits for its accounting records and a checked GSTIN."""

from unittest.mock import patch

import frappe

from central.billing.revenue import gst_status, invoicing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-invoice-hold"
CLUSTER = "ap-south-1"
PLAN = "bundle-invoice-hold"
GSTIN = "27AAPFU0939F1ZV"
SYNCED = {"profile_id": "CUST-1", "address_id": "ADDR-1", "contact_id": "CONT-1"}
CUSTOMER_SYNC = "central.billing.ingester.customer._enqueue"
GSTIN_LOOKUP = "central.billing.revenue.gst_status._enqueue_refresh"


class InvoiceHoldTestCase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		complete_billing_profile(TEAM)
		self.invoice = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")
		self._conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		self._conf.start()
		self._release = patch("central.billing.revenue.invoicing.run.release_held_drafts")
		self._release.start()

	def tearDown(self):
		self._release.stop()
		self._conf.stop()

	def _profile(self, **values):
		frappe.db.set_value("Billing Profile", TEAM, values)

	def _open(self):
		with patch(CUSTOMER_SYNC) as sync, patch(GSTIN_LOOKUP) as lookup:
			result = invoicing.open_and_collect(self.invoice)
		return result, sync, lookup

	def _invoice(self):
		return frappe.get_doc("Invoice", self.invoice)


class TestHeld(InvoiceHoldTestCase):
	def test_unsynced_records_hold_the_draft_and_queue_their_sync(self):
		self._profile(profile_id="CUST-1")  # address and contact still missing
		result, sync, _ = self._open()
		self.assertEqual(result["held"], "accounting_sync")
		sync.assert_called_once_with(TEAM)
		inv = self._invoice()
		self.assertEqual((inv.status, inv.hold_reason), ("Draft", "Accounting Sync"))

	def test_unchecked_gstin_holds_the_draft_and_queues_its_lookup(self):
		self._profile(**SYNCED, gstin=GSTIN, gst_status=None)
		result, _, lookup = self._open()
		self.assertEqual(result["held"], "gstin_check")
		lookup.assert_called_once_with(TEAM)
		self.assertEqual(self._invoice().hold_reason, "GSTIN Check")

	def test_a_gstin_waiting_out_a_failed_lookup_is_not_asked_again(self):
		retry = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=2)
		self._profile(**SYNCED, gstin=GSTIN, gst_status=None, gst_status_retry_after=retry)
		result, _, lookup = self._open()
		self.assertEqual(result["held"], "gstin_check")
		lookup.assert_not_called()


class TestIssued(InvoiceHoldTestCase):
	def test_synced_team_without_a_gstin_opens(self):
		self._profile(**SYNCED, gstin=None)
		result, _, _ = self._open()
		self.assertTrue(result["claimed"])
		self.assertFalse(self._invoice().hold_reason)

	def test_checked_gstin_opens_with_it(self):
		self._profile(**SYNCED, gstin=GSTIN, gst_status="Active")
		self._open()
		self.assertEqual(self._invoice().customer_gstin, GSTIN)

	def test_tax_is_recomputed_from_the_checked_gstin(self):
		# Drafted untaxed; by the time it opens the team is SEZ and its GSTIN lapsed.
		self._profile(**SYNCED, gstin=GSTIN, gst_status=None)
		frappe.get_doc(
			{
				"doctype": "Tax Profile",
				"team": TEAM,
				"output_tax_type": "GST",
				"output_tax_rate": 18,
				"zero_rated": 1,
				"zero_rating_reason": "SEZ",
			}
		).insert(ignore_permissions=True)
		self._open()
		with patch(CUSTOMER_SYNC):
			gst_status.store(TEAM, GSTIN, {"status": "Cancelled"})
		self._open()
		inv = self._invoice()
		self.assertEqual(inv.status, "Open")
		self.assertFalse(inv.customer_gstin)  # billed as unregistered
		self.assertEqual(inv.output_tax_amount, 180.0)  # and SEZ no longer applies
		self.assertEqual(inv.total, 1180.0)

	def test_nothing_is_held_when_sync_is_off(self):
		frappe.local.conf["enable_erpnext_sync"] = 0
		self._profile(gstin=GSTIN, gst_status=None)
		result, _, _ = self._open()
		self.assertTrue(result["claimed"])

	def test_staging_trial_needs_no_records(self):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		result, sync, _ = self._open()
		self.assertTrue(result["claimed"])
		sync.assert_not_called()


class TestReleased(InvoiceHoldTestCase):
	def test_a_checked_gstin_releases_the_team(self):
		self._profile(**SYNCED, gstin=GSTIN, gst_status=None)
		with patch("central.billing.ingester.customer.enqueue_for"):
			gst_status.store(TEAM, GSTIN, {"status": "Active"})
		from central.billing.revenue.invoicing import run

		run.release_held_drafts.assert_called_with(TEAM)

	def test_the_last_sync_step_releases_the_team(self):
		from central.billing.ingester import customer
		from central.billing.revenue.invoicing import run

		self._profile(**SYNCED)
		with patch("central.billing.ingester.customer.put"):
			customer.sync_customer_profile(TEAM)
		frappe.cache.delete(customer._lock_name(TEAM))
		run.release_held_drafts.assert_called_with(TEAM)
