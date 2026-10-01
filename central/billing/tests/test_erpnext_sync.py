# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Issuing the statutory Sales Invoice, using advances, and recording card payments."""

from unittest.mock import patch

import frappe

from central.billing.ingester import erpnext_sync
from central.billing.tests.accounting_fake import (
	COMPANY_GSTIN,
	IN_STATE,
	OUT_STATE,
	FakeAccountingSystem,
	billing_team,
	configure_accounting,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-erp"
GSTIN = "27AABCT1111T1Z5"


class SyncTestCase(IntegrationTestCase):
	def setUp(self):
		conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		conf.start()
		self.addCleanup(conf.stop)
		configure_accounting()
		self.remote = FakeAccountingSystem()
		self.enterContext(self.remote.patches())

	def _invoice(
		self, team=TEAM, currency="INR", subtotal=8000, tax=1440, credit=0, paid=0, month=8, advance=0
	):
		start = f"2026-{month:02d}-01"
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": team,
					"invoice_type": "Billable",
					"status": "Paid",
					"period_start": start,
					"period_end": str(frappe.utils.get_last_day(start)),
					"currency": currency,
					"subtotal": subtotal,
					"output_tax_amount": tax,
					"total": subtotal + tax,
					"credit_applied": credit,
					"advance_applied": advance,
					"amount_paid": paid,
					"customer_gstin": frappe.db.get_value("Billing Profile", team, "gstin"),
					"items": [
						{
							"plan": "Business VM",
							"subscription_resource": "vm-1",
							"rate": subtotal,
							"amount": subtotal,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _sales_invoice(self):
		return self.remote.posts("Sales Invoice")[-1]


class TestIssue(SyncTestCase):
	def test_registered_team_in_the_company_state(self):
		billing_team(TEAM, gstin=GSTIN)
		inv = self._invoice()
		out = erpnext_sync.sync_invoice(inv)

		si = self._sales_invoice()
		self.assertEqual(si["docstatus"], 1)
		self.assertEqual(si["naming_series"], "B2B/.TFY./.#####")
		self.assertEqual(si["debit_to"], "Debtors - TC")
		self.assertEqual(si["company_gstin"], COMPANY_GSTIN)
		self.assertEqual(si["billing_address_gstin"], GSTIN)
		self.assertEqual(si["gst_category"], "Registered Regular")
		self.assertEqual(si["place_of_supply"], "27-Maharashtra")
		self.assertEqual(si["taxes_and_charges"], IN_STATE)
		self.assertEqual([t["rate"] for t in si["taxes"]], [9, 9])
		self.assertEqual(si["items"][0]["item_code"], "Cloud Hosting")
		self.assertIn(f"Central invoice {inv}", si["remarks"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "erpnext_invoice"), out["synced"])

	def test_unregistered_team_in_another_state(self):
		billing_team(TEAM, state="Karnataka")
		erpnext_sync.sync_invoice(self._invoice())
		si = self._sales_invoice()
		self.assertEqual(si["naming_series"], "B2C/.TFY./.#####")
		self.assertEqual(si["gst_category"], "Unregistered")
		self.assertEqual(si["taxes_and_charges"], OUT_STATE)

	def test_overseas_team_carries_no_gst(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		erpnext_sync.sync_invoice(self._invoice(currency="USD", subtotal=1000, tax=0))
		si = self._sales_invoice()
		self.assertEqual(si["naming_series"], "EXP/.TFY./.#####")
		self.assertEqual(si["debit_to"], "Debtors USD - TC")
		self.assertEqual((si["gst_category"], si["place_of_supply"]), ("Overseas", "96-Other Countries"))
		self.assertEqual(si["taxes"], [])

	def test_an_invoice_already_issued_is_adopted_not_repeated(self):
		billing_team(TEAM, gstin=GSTIN)
		inv = self._invoice()
		self.remote.records[("Sales Invoice", "SINV-EXISTING")] = {"remarks": f"Central invoice {inv}"}
		out = erpnext_sync.sync_invoice(inv)
		self.assertEqual(out["synced"], "SINV-EXISTING")
		self.assertEqual(self.remote.posts("Sales Invoice"), [])


class TestAdvances(SyncTestCase):
	def _top_up(self, advance_id="RV-1", credit=10000):
		frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": TEAM,
				"entry_type": "Credit",
				"amount": credit,
				"tax_amount": credit * 0.18,
				"currency": "INR",
				"gateway_payment_id": f"Stripe:pi_{advance_id}",
				"advance_id": advance_id,
			}
		).insert(ignore_permissions=True)
		if advance_id:
			self.remote.records[("Payment Entry", advance_id)] = {"unallocated_amount": credit}

	def test_the_credit_used_is_allocated_from_the_advance(self):
		billing_team(TEAM, gstin=GSTIN)
		self._top_up()
		erpnext_sync.sync_invoice(self._invoice(credit=8000, advance=8000))
		advance = self._sales_invoice()["advances"][0]
		self.assertEqual((advance["reference_name"], advance["allocated_amount"]), ("RV-1", 8000))

	def test_oldest_advance_first_then_the_next(self):
		billing_team(TEAM, gstin=GSTIN)
		self._top_up("RV-1", credit=1000)
		self._top_up("RV-2", credit=10000)
		erpnext_sync.sync_invoice(self._invoice(credit=8000, advance=8000))
		rows = [(a["reference_name"], a["allocated_amount"]) for a in self._sales_invoice()["advances"]]
		self.assertEqual(rows, [("RV-1", 1000), ("RV-2", 7000)])

	def test_promotional_credit_is_noted_as_not_backed(self):
		billing_team(TEAM, gstin=GSTIN)
		self._top_up()
		erpnext_sync.sync_invoice(self._invoice(credit=9000, advance=8000))
		self.assertIn("not backed by an advance: 1000", self._sales_invoice()["remarks"])

	def test_waits_for_a_top_up_whose_advance_has_not_synced(self):
		billing_team(TEAM, gstin=GSTIN)
		self._top_up(advance_id=None)
		out = erpnext_sync.sync_invoice(self._invoice(credit=8000, advance=8000))
		self.assertTrue(out["retry_scheduled"])
		self.assertEqual(self.remote.posts("Sales Invoice"), [])


class TestCardPayment(SyncTestCase):
	def _captured(self, inv, currency="USD", amount=1000):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": inv,
					"team": TEAM,
					"gateway": "Stripe",
					"amount": amount,
					"currency": currency,
					"status": "Captured",
					"gateway_transaction_id": "pi_card_1",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_card_payment_is_recorded_against_the_invoice(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		self.remote.conversion_rate = 95.83
		inv = self._invoice(currency="USD", subtotal=1000, tax=0, paid=1000)
		self._captured(inv)
		out = erpnext_sync.sync_invoice(inv)

		payment = self.remote.posts("Payment Entry")[-1]
		self.assertEqual(payment["reference_no"], "pi_card_1")
		self.assertEqual(payment["paid_from"], "Debtors USD - TC")
		self.assertEqual(payment["paid_to"], "Stripe Clearing USD - TC")
		self.assertEqual((payment["paid_amount"], payment["received_amount"]), (1000, 1000))
		self.assertEqual(payment["source_exchange_rate"], 95.83)
		self.assertEqual(payment["references"][0]["reference_name"], out["synced"])
		self.assertEqual(frappe.db.get_value("Invoice", inv, "payment_record_id"), out["payment"])

	def test_a_retry_after_the_payment_failed_does_not_issue_twice(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		inv = self._invoice(currency="USD", subtotal=1000, tax=0, paid=1000)
		self._captured(inv)
		self.remote.fail_on.add("Payment Entry")
		self.assertTrue(erpnext_sync.sync_invoice(inv)["retry_scheduled"])
		self.assertTrue(frappe.db.get_value("Invoice", inv, "erpnext_invoice"))  # issued, kept

		erpnext_sync.sync_invoice(inv)
		self.assertEqual(len(self.remote.posts("Sales Invoice")), 1)
		self.assertEqual(len(self.remote.posts("Payment Entry")), 1)


class TestFailureIsolation(SyncTestCase):
	def test_sync_off_does_nothing(self):
		billing_team(TEAM, gstin=GSTIN)
		frappe.local.conf["enable_erpnext_sync"] = 0
		self.assertEqual(erpnext_sync.sync_invoice(self._invoice())["skipped"], "sync_off")

	def test_team_without_a_customer_retries_later(self):
		billing_team(TEAM, gstin=GSTIN)
		frappe.db.set_value("Billing Profile", TEAM, "profile_id", None)
		with patch("central.billing.ingester.customer._enqueue"):
			out = erpnext_sync.sync_invoice(self._invoice())
		self.assertTrue(out["retry_scheduled"])
		self.assertEqual(self.remote.posted, [])

	def test_backoff_grows_then_alerts_ops(self):
		billing_team(TEAM, gstin=GSTIN)
		inv = self._invoice()
		results = []
		for _ in range(3):
			self.remote.fail_on.add("Sales Invoice")
			results.append(erpnext_sync.sync_invoice(inv))
		self.assertEqual([r.get("backoff_seconds") for r in results[:2]], [60, 120])
		doc = frappe.get_doc("Invoice", inv)
		self.assertEqual((doc.status, doc.erpnext_sync_status), ("Paid", "Failed"))
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv}, pluck="content"
		)
		self.assertTrue(any("ERPNext sync failed" in c for c in comments))

	def test_unbillable_and_unpaid_are_skipped(self):
		billing_team(TEAM, gstin=GSTIN)
		cost = self._invoice(month=5)
		frappe.db.set_value("Invoice", cost, "invoice_type", "Cost Report")
		unpaid = self._invoice(month=6)
		frappe.db.set_value("Invoice", unpaid, "status", "Open")
		self.assertEqual(erpnext_sync.sync_invoice(cost)["skipped"], "not_billable")
		self.assertEqual(erpnext_sync.sync_invoice(unpaid)["skipped"], "not_paid")


class TestWhenItSyncs(SyncTestCase):
	def test_enqueued_after_commit(self):
		with patch("central.billing.ingester.erpnext_sync.frappe.enqueue") as enqueue:
			erpnext_sync.enqueue_invoice_sync("INV-1")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_an_invoice_the_wallet_pays_in_full_is_synced(self):
		from central.billing.revenue import credits
		from central.billing.revenue.invoicing.lifecycle import open_and_collect

		billing_team(TEAM, gstin=GSTIN)
		frappe.db.set_value("Tax Profile", TEAM, {"output_tax_type": "GST", "output_tax_rate": 18})
		inv = self._invoice(credit=0)
		frappe.db.set_value("Invoice", inv, "status", "Draft")
		credits.grant_promotional_credits(TEAM, 20000, "INR")
		with patch("central.billing.ingester.erpnext_sync.enqueue_invoice_sync") as enqueue:
			self.assertEqual(open_and_collect(inv)["status"], "Paid")
		enqueue.assert_called_once_with(inv)
