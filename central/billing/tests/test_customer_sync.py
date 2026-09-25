# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Customer, address and contact kept in step with the Billing Profile."""

from unittest.mock import patch

import frappe

from central.billing.ingester import customer
from central.billing.payments.provisioning import apply_gst_category, ensure_tax_profile
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-customer-sync"
POST = "central.billing.ingester.customer.post"
PUT = "central.billing.ingester.customer.put"


def created(*names):
	"""A fake `post` answering each call with the next record name."""
	return [frappe._dict(name=n) for n in names]


class CustomerSyncTestCase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		self._conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		self._conf.start()

	def tearDown(self):
		self._conf.stop()

	def _ids(self):
		return frappe.db.get_value(
			"Billing Profile", TEAM, ["profile_id", "address_id", "contact_id"], as_dict=True
		)


class TestCreate(CustomerSyncTestCase):
	def test_creates_all_three_and_keeps_their_ids(self):
		with patch(POST, side_effect=created("CUST-1", "ADDR-1", "CONT-1")) as post:
			customer.sync_customer_profile(TEAM)
		self.assertEqual(
			self._ids(), {"profile_id": "CUST-1", "address_id": "ADDR-1", "contact_id": "CONT-1"}
		)
		address, contact = post.call_args_list[1].args[1], post.call_args_list[2].args[1]
		self.assertEqual(address["links"][0]["link_name"], "CUST-1")
		self.assertEqual(contact["links"][0]["link_name"], "CUST-1")

	def test_failure_half_way_resumes_without_a_second_customer(self):
		with patch(POST, side_effect=[frappe._dict(name="CUST-1"), ConnectionError("down")]):
			with self.assertRaises(ConnectionError):
				customer.sync_customer_profile(TEAM)
		self.assertEqual(self._ids().profile_id, "CUST-1")

		with patch(POST, side_effect=created("ADDR-1", "CONT-1")) as post, patch(PUT) as put:
			customer.sync_customer_profile(TEAM)
		self.assertEqual(put.call_args.args[0], "api/resource/Customer/CUST-1")
		self.assertEqual(
			[c.args[0] for c in post.call_args_list], ["api/resource/Address", "api/resource/Contact"]
		)
		self.assertEqual(self._ids().contact_id, "CONT-1")


class TestUpdate(CustomerSyncTestCase):
	def test_updates_each_record_in_place(self):
		frappe.db.set_value(
			"Billing Profile", TEAM, {"profile_id": "CUST 1", "address_id": "ADDR-1", "contact_id": "CONT-1"}
		)
		with patch(POST) as post, patch(PUT) as put:
			customer.sync_customer_profile(TEAM)
		post.assert_not_called()
		self.assertEqual(
			[c.args[0] for c in put.call_args_list],
			["api/resource/Customer/CUST%201", "api/resource/Address/ADDR-1", "api/resource/Contact/CONT-1"],
		)


class TestWhenToSync(CustomerSyncTestCase):
	def _save(self, **values):
		doc = frappe.get_doc("Billing Profile", TEAM)
		doc.update(values)
		with patch("central.billing.ingester.customer._enqueue") as enqueue:
			doc.save(ignore_permissions=True)
		return enqueue

	def test_unsynced_complete_profile_is_queued(self):
		self._save(phone="8888888888").assert_called_once_with(TEAM)

	def test_synced_profile_waits_for_a_synced_field_to_change(self):
		frappe.db.set_value("Billing Profile", TEAM, "profile_id", "CUST-1")
		self._save(min_balance=10).assert_not_called()
		self._save(legal_name="Renamed Ltd").assert_called_once_with(TEAM)

	def test_incomplete_profile_is_not_queued(self):
		self._save(legal_name="", phone="7777777777").assert_not_called()

	def test_staging_trial_is_not_queued(self):
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		self._save(phone="6666666666").assert_not_called()

	def test_nothing_is_queued_when_sync_is_off(self):
		frappe.local.conf["enable_erpnext_sync"] = 0
		self._save(phone="5555555555").assert_not_called()


class TestPending(CustomerSyncTestCase):
	def test_picks_complete_profiles_missing_a_record(self):
		frappe.db.set_value("Billing Profile", TEAM, {"profile_id": "CUST-1", "address_id": "ADDR-1"})
		self.assertIn(TEAM, customer._pending_teams())
		frappe.db.set_value("Billing Profile", TEAM, "contact_id", "CONT-1")
		self.assertNotIn(TEAM, customer._pending_teams())

	def test_skips_incomplete_profiles(self):
		frappe.db.set_value("Billing Profile", TEAM, "legal_name", None)
		self.assertNotIn(TEAM, customer._pending_teams())


class TestContactPayload(CustomerSyncTestCase):
	def test_leaves_out_what_is_blank(self):
		frappe.db.set_value("Billing Profile", TEAM, {"email": None, "phone": None})
		payload = customer._contact_payload(frappe.get_doc("Billing Profile", TEAM))
		self.assertEqual(payload["phone_nos"], [])
		self.assertTrue(all(e["email_id"] for e in payload["email_ids"]))
		self.assertTrue(payload["first_name"])


class TestGstCategory(CustomerSyncTestCase):
	def test_sez_is_zero_rated_and_undone_when_it_changes(self):
		apply_gst_category(TEAM, "SEZ")
		profile = frappe.get_doc("Tax Profile", TEAM)
		self.assertEqual((profile.zero_rated, profile.zero_rating_reason), (1, "SEZ"))
		apply_gst_category(TEAM, "Registered Regular")
		profile.reload()
		self.assertEqual(profile.zero_rated, 0)

	def test_other_zero_rating_is_left_alone(self):
		profile = ensure_tax_profile(TEAM)
		profile.update({"zero_rated": 1, "zero_rating_reason": "Overseas"})
		profile.save(ignore_permissions=True)
		apply_gst_category(TEAM, "Registered Regular")
		profile.reload()
		self.assertEqual((profile.zero_rated, profile.zero_rating_reason), (1, "Overseas"))
