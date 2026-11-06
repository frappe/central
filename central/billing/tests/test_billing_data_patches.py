# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Each billing data patch repairs the state it was written for."""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from central.billing import settings
from central.billing.doctype.invoice.invoice import period_key_for
from central.billing.platform import readiness
from central.billing.revenue import credits
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	billing_settings,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)
from central.patches.v0_0 import (
	allow_storage_in_vm_plans,
	charge_gst_to_indian_tax_profiles,
	clear_retired_scenario_ladder_overrides,
	expire_promotional_credit_and_clear_unbooked_wallets,
	mark_waived_invoices_as_not_synced,
	merge_invoice_draft_and_open_into_outstanding,
	move_internal_flag_to_billing_profile,
	remove_webhook_events_of_another_product,
	repoint_billing_records_to_renamed_region,
	set_dunning_ladder_settings,
	set_payment_date_on_open_invoices,
	set_suspension_date_on_open_invoices,
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

	def test_storage_is_added_to_vm_plans_once(self):
		filters = {
			"parenttype": "Plan Category",
			"parent": "VM Plans",
			"parentfield": "allowed_resource_types",
			"resource_type": "Storage",
		}
		frappe.db.delete("Plan Category Resource Type", filters)
		existing_types = frappe.get_all(
			"Plan Category Resource Type",
			filters={"parenttype": "Plan Category", "parent": "VM Plans"},
			fields=["name", "resource_type"],
			order_by="name",
		)
		plan = make_plan(
			"storage-patch-preserves-plan",
			includes=[{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"}],
		)
		plan_includes = frappe.get_all(
			"Plan Includes",
			filters={"parenttype": "Plan", "parent": plan},
			fields=["resource_type", "quantity", "unit"],
		)

		allow_storage_in_vm_plans.execute()
		allow_storage_in_vm_plans.execute()

		self.assertEqual(frappe.db.count("Plan Category Resource Type", filters), 1)
		self.assertEqual(
			frappe.get_all(
				"Plan Category Resource Type",
				filters={
					"parenttype": "Plan Category",
					"parent": "VM Plans",
					"resource_type": ["!=", "Storage"],
				},
				fields=["name", "resource_type"],
				order_by="name",
			),
			existing_types,
		)
		self.assertEqual(
			frappe.get_all(
				"Plan Includes",
				filters={"parenttype": "Plan", "parent": plan},
				fields=["resource_type", "quantity", "unit"],
			),
			plan_includes,
		)

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
		frappe.db.delete("Billing Profile", {"team": OTHER_TEAM})
		# The DocType no longer has the old columns, so a fresh site has none to fill.
		old_rows = [
			frappe._dict(team=TEAM, internal_reason="Our own servers"),
			frappe._dict(team=OTHER_TEAM, internal_reason=None),
		]
		patch_module = move_internal_flag_to_billing_profile
		with (
			patch.object(frappe.db, "has_column", return_value=True),
			patch.object(patch_module, "internal_tax_profiles", return_value=old_rows),
		):
			patch_module.execute()

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


class TestSetPaymentDateOnOpenInvoices(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)

	def test_an_open_invoice_gets_the_date_it_was_issued(self):
		open_invoice = _insert_invoice("Outstanding", "2026-05-31", due_date="2026-06-14")
		dated = _insert_invoice("Outstanding", "2026-04-30", due_date="2026-05-14", payment_date="2026-05-05")
		for invoice, occurred_at in ((open_invoice, "2026-06-03 10:00:00"), (dated, "2026-05-01 10:00:00")):
			frappe.get_doc(
				{
					"doctype": "Billing Event",
					"team": TEAM,
					"event_type": "Invoice Issued",
					"subject_doctype": "Invoice",
					"subject": invoice,
					"occurred_at": occurred_at,
				}
			).db_insert()

		set_payment_date_on_open_invoices.execute()

		self.assertEqual(str(frappe.db.get_value("Invoice", open_invoice, "payment_date")), "2026-06-03")
		self.assertEqual(str(frappe.db.get_value("Invoice", dated, "payment_date")), "2026-05-05")


class TestSetSuspensionDateOnOpenInvoices(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		singles = frappe.qb.DocType("Singles")
		stored = (
			frappe.qb.from_(singles)
			.select(singles.value)
			.where(singles.doctype == "Billing Settings")
			.where(singles.field == "suspend_after_days")
			.run(pluck=True)
		)
		self.addCleanup(self._store_old_suspend_after_days, stored[0] if stored else None)

	def _store_old_suspend_after_days(self, value) -> None:
		"""The removed field lives on only as a Singles row, so the test writes that row."""
		singles = frappe.qb.DocType("Singles")
		frappe.qb.from_(singles).delete().where(singles.doctype == "Billing Settings").where(
			singles.field == "suspend_after_days"
		).run()
		if value is not None:
			frappe.qb.into(singles).columns(singles.doctype, singles.field, singles.value).insert(
				"Billing Settings", "suspend_after_days", value
			).run()

	def test_an_open_invoice_keeps_the_suspension_date_of_the_old_ladder(self):
		self._store_old_suspend_after_days("12")
		deferred = _insert_invoice(
			"Outstanding", "2026-05-31", due_date="2026-06-08", dunning_starts_on="2026-06-10"
		)
		overdue = _insert_invoice("Overdue", "2026-04-30", due_date="2026-05-08")
		dated = _insert_invoice("Outstanding", "2026-03-31", due_date="2026-04-08", suspends_on="2026-04-15")
		paid = _insert_invoice("Paid", "2026-02-28", due_date="2026-03-08")

		set_suspension_date_on_open_invoices.execute()

		suspends_on = {
			name: str(frappe.db.get_value("Invoice", name, "suspends_on") or "")
			for name in (deferred, overdue, dated, paid)
		}
		self.assertEqual(suspends_on[deferred], "2026-06-22")
		self.assertEqual(suspends_on[overdue], "2026-05-20")
		self.assertEqual(suspends_on[dated], "2026-04-15")
		self.assertEqual(suspends_on[paid], "")
		self.assertEqual(str(frappe.db.get_value("Invoice", deferred, "dunning_starts_on")), "2026-06-10")

	def test_an_unsaved_old_setting_reads_as_its_default(self):
		self._store_old_suspend_after_days(None)
		invoice = _insert_invoice("Outstanding", "2026-05-31", due_date="2026-06-08")

		set_suspension_date_on_open_invoices.execute()

		self.assertEqual(str(frappe.db.get_value("Invoice", invoice, "suspends_on")), "2026-06-22")


class TestSetDunningLadderSettings(IntegrationTestCase):
	def test_the_ladder_suspends_on_the_15th_and_terminates_10_days_later(self):
		names = ("dunning_retry_interval_days", "suspension_day", "terminate_after_days")
		before = {name: frappe.db.get_single_value("Billing Settings", name) for name in names}
		self.addCleanup(frappe.db.set_single_value, "Billing Settings", before)
		frappe.db.set_single_value(
			"Billing Settings",
			{"dunning_retry_interval_days": 5, "suspension_day": 20, "terminate_after_days": 30},
		)

		set_dunning_ladder_settings.execute()

		after = {name: frappe.db.get_single_value("Billing Settings", name) for name in names}
		self.assertEqual(after, dict(zip(names, (2, 15, 10), strict=True)))


class TestClearRetiredScenarioLadderOverrides(IntegrationTestCase):
	def test_a_saved_scenario_reads_the_live_ladder(self):
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": "Old ladder",
				"period_start": "2026-09-01",
				"terminate_after_days": 44,
				"invoice_due_days": 5,
			}
		)
		doc.db_insert()
		self.addCleanup(frappe.db.delete, "Billing Scenario", {"name": doc.name})
		old_values = {"dunning_retry_days": "1, 3, 7", "suspend_after_days": 14}
		retired = [column for column in old_values if frappe.db.has_column("Billing Scenario", column)]
		# A fresh install never had the retired columns, so there is nothing old to seed.
		for column in retired:
			frappe.db.set_value(
				"Billing Scenario", doc.name, column, old_values[column], update_modified=False
			)

		clear_retired_scenario_ladder_overrides.execute()

		cleared = frappe.get_doc("Billing Scenario", doc.name)
		self.assertEqual(cleared.terminate_after_days, 0)
		self.assertEqual(cleared.overrides(), {"invoice_due_days": 5})
		for column in retired:
			self.assertFalse(frappe.db.get_value("Billing Scenario", doc.name, column))


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

	def test_an_indian_tax_profile_without_gst_is_charged_gst(self):
		complete_billing_profile(TEAM)
		frappe.db.delete("Tax Profile", {"team": TEAM})
		frappe.get_doc({"doctype": "Tax Profile", "team": TEAM, "output_tax_type": "None"}).db_insert()

		with billing_settings(default_gst_rate=18):
			charge_gst_to_indian_tax_profiles.execute()

		values = frappe.db.get_value("Tax Profile", TEAM, ["output_tax_type", "output_tax_rate"])
		self.assertEqual(values, ("GST", 18))

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


def _wallet(balance: float, team: str = TEAM, currency: str = "INR") -> str:
	wallet = frappe.get_doc(
		{
			"doctype": "Credit Wallet",
			"name": credits.wallet_name(team, currency),
			"team": team,
			"currency": currency,
			"balance": balance,
		}
	)
	wallet.db_insert()
	return wallet.name


def _ledger_entry(entry_type: str, amount: float, team: str = TEAM, **fields) -> str:
	entry = frappe.get_doc(
		{
			"doctype": "Credit Ledger Entry",
			"team": team,
			"currency": "INR",
			"entry_type": entry_type,
			"amount": amount,
			**fields,
		}
	)
	entry.db_insert()
	return entry.name


def _repair_entries(wallet: str) -> list:
	return frappe.get_all(
		"Credit Ledger Entry",
		filters={"reference_type": "Ledger Repair", "reference_name": wallet},
		fields=["entry_type", "amount", "paid_in", "running_balance", "expires_on", "created_at"],
	)


class TestBookMissingWalletCredit(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)

	def test_a_wallet_above_its_ledger_gets_the_missing_credit_booked(self):
		wallet = _wallet(200)
		_ledger_entry("Debit", 300, running_balance=200, reference_type="Invoice")

		expire_promotional_credit_and_clear_unbooked_wallets.book_missing_wallet_credit()

		(repair,) = _repair_entries(wallet)
		self.assertEqual((repair.entry_type, repair.amount, repair.paid_in), ("Credit", 500, 0))
		self.assertEqual(repair.running_balance, 200)
		created = frappe.db.get_value("Credit Wallet", wallet, "creation")
		days = settings.promotional_credit_validity_days()
		self.assertEqual(repair.expires_on, add_days(getdate(created), days))
		self.assertEqual(frappe.db.get_value("Credit Wallet", wallet, "balance"), 200)
		self.assertEqual(credits.ledger_balance(TEAM, "INR"), 200)

	def test_a_wallet_with_no_entries_gets_a_credit_of_its_balance(self):
		wallet = _wallet(75.5)

		expire_promotional_credit_and_clear_unbooked_wallets.book_missing_wallet_credit()

		(repair,) = _repair_entries(wallet)
		self.assertEqual(repair.amount, 75.5)
		self.assertEqual(credits.ledger_balance(TEAM, "INR"), 75.5)
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 75.5)
		credits.lock_team_wallet(TEAM, "INR")

	def test_a_wallet_below_its_ledger_is_left_alone(self):
		wallet = _wallet(100)
		_ledger_entry("Credit", 300, running_balance=300, reference_type="Promotion")

		expire_promotional_credit_and_clear_unbooked_wallets.book_missing_wallet_credit()

		self.assertEqual(_repair_entries(wallet), [])
		self.assertEqual(frappe.db.get_value("Credit Wallet", wallet, "balance"), 100)


def _refund(promotional_amount: float = 0) -> str:
	refund = frappe.get_doc(
		{
			"doctype": "Refund",
			"team": TEAM,
			"amount": 50,
			"currency": "INR",
			"destination": "Wallet",
			"promotional_amount": promotional_amount,
		}
	)
	refund.db_insert()
	return refund.name


class TestSetExpiryOnPromotionalCredit(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)

	def test_returned_unpaid_credit_expires_and_admin_credit_does_not(self):
		promotional_refund, overcharge_refund = _refund(promotional_amount=50), _refund()
		expiring = [
			_ledger_entry("Credit", 100, reference_type="Promotion"),
			_ledger_entry("Credit", 40, reference_type="Invoice", reference_name="INV-RETURNED"),
			_ledger_entry("Credit", 50, reference_type="Refund", reference_name=promotional_refund),
		]
		kept = [
			_ledger_entry("Credit", 30, reference_type="Admin"),
			_ledger_entry("Credit", 50, reference_type="Refund", reference_name=overcharge_refund),
			_ledger_entry("Credit", 60, reference_type="Invoice", reference_name="INV-PAID", paid_in=1),
		]
		self.assertEqual(sorted(self._flagged_by_readiness()), sorted(expiring))

		expire_promotional_credit_and_clear_unbooked_wallets.set_expiry_on_promotional_credit()

		for entry in expiring:
			self.assertIsNotNone(frappe.db.get_value("Credit Ledger Entry", entry, "expires_on"))
		for entry in kept:
			self.assertIsNone(frappe.db.get_value("Credit Ledger Entry", entry, "expires_on"))
		self.assertEqual(self._flagged_by_readiness(), [])

	def _flagged_by_readiness(self) -> list[str]:
		return [v.subject for v in readiness.check_promotional_credit_expires() if v.team == TEAM]


def _stored_event(event_id: str, raw_payload: str) -> str:
	event = frappe.get_doc(
		{
			"doctype": "Webhook Event",
			"gateway": "Stripe",
			"gateway_event_id": event_id,
			"event_type": "payment_intent.succeeded",
			"status": "Ignored",
			"raw_payload": raw_payload,
		}
	)
	event.db_insert()
	frappe.get_doc(
		{
			"doctype": "Billing Event",
			"event_type": "Webhook Event Ignored",
			"subject_doctype": "Webhook Event",
			"subject": event.name,
		}
	).db_insert()
	return event.name


def _stripe_body(event_id: str, gateway_object: dict) -> str:
	return json.dumps(
		{"id": event_id, "type": "payment_intent.succeeded", "data": {"object": gateway_object}}
	)


class TestRemoveWebhookEventsOfAnotherProduct(IntegrationTestCase):
	def setUp(self):
		make_stripe_gateway()

	def test_only_events_of_another_product_are_removed(self):
		order = frappe.get_doc(
			{"doctype": "Top-up Order", "team": TEAM, "gateway": "Stripe", "currency": "INR"}
		)
		order.db_insert()
		other_product = _stored_event("evt_v1", _stripe_body("evt_v1", {"id": "pi_v1"}))
		central = _stored_event(
			"evt_central", _stripe_body("evt_central", {"metadata": {"receipt": order.name}})
		)
		unreadable = _stored_event("evt_unreadable", "{not json")

		with patch.object(remove_webhook_events_of_another_product, "PAGE_SIZE", 1):
			remove_webhook_events_of_another_product.execute()

		self.assertFalse(frappe.db.exists("Webhook Event", other_product))
		self.assertFalse(frappe.db.exists("Billing Event", {"subject": other_product}))
		for kept in (central, unreadable):
			self.assertTrue(frappe.db.exists("Webhook Event", kept))
			self.assertTrue(frappe.db.exists("Billing Event", {"subject": kept}))
