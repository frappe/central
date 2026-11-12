from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.services.doctype.ai_trial_key.ai_trial_key import (
	AITrialKey,
	refill_trial_keys,
	revoke_available_keys,
)

TRIAL_KEYS = "central.services.doctype.ai_trial_key.ai_trial_key"


class TestAITrialKey(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		if not frappe.db.exists("Product", "raven"):
			frappe.get_doc(
				{"doctype": "Product", "product_key": "raven", "title": "Raven", "signup_app": "raven"}
			).insert()
		settings = frappe.get_doc("AI Settings")
		settings.update(
			{
				"base_url": "https://grove.test",
				"control_api_key": "control",
				"control_api_secret": "secret",
				"trial_products": [{"product": "raven", "pool_size": 1}],
			}
		)
		settings.save()
		frappe.clear_document_cache("AI Settings", "AI Settings")

	def test_a_paused_pool_is_not_refilled_but_the_retries_run(self):
		frappe.db.set_single_value("AI Settings", "pause_pool_refill", 1)

		with (
			patch(f"{TRIAL_KEYS}.AITrialKey.provision") as provision,
			patch(f"{TRIAL_KEYS}.retry_stale") as retry_stale,
		):
			refill_trial_keys()

		provision.assert_not_called()
		retry_stale.assert_called_once()

	def test_paused_assignment_leaves_the_ready_key_in_the_pool(self):
		key = frappe.get_doc(
			{"doctype": "AI Trial Key", "grove_key": "key-1", "product": "raven", "api_key": "secret"}
		).insert()
		frappe.db.set_single_value("AI Settings", "pause_key_assignment", 1)
		action = Mock(is_free_trial=1, team="TEAM-00001", product="raven")
		action.name = "action-1"

		self.assertIsNone(AITrialKey.assign(action))
		self.assertEqual(frappe.db.get_value("AI Trial Key", key.name, "status"), "Available")

	def test_a_revoked_record_is_dropped_with_its_secret_once_its_days_have_passed(self):
		aged = add_to_date(now_datetime(), days=-31)
		gone = self.key("Revoked", modified=aged)
		failed = self.key("Conversion Failed", revoked=1, modified=aged)
		fresh = self.key("Revoked")
		pending = self.key("Conversion Failed", modified=aged)
		live = self.key("Assigned", modified=aged)

		AITrialKey.clear_old_logs(days=30)

		self.assertEqual(
			sorted(frappe.get_all("AI Trial Key", pluck="name")),
			sorted([fresh.name, pending.name, live.name]),
		)
		for key in (gone, failed):
			with self.assertRaisesRegex(frappe.ValidationError, "not found"):
				key.get_password("api_key")
		self.assertEqual(fresh.get_password("api_key"), "secret")

	def test_revoke_available_keys_leaves_the_assigned_ones(self):
		ready, taken, gone = self.key("Available"), self.key("Assigned"), self.key("Revoked")

		with patch(f"{TRIAL_KEYS}.frappe.enqueue") as enqueue:
			self.assertEqual(revoke_available_keys(), 1)

		self.assertEqual(
			[frappe.db.get_value("AI Trial Key", k.name, "status") for k in (ready, taken, gone)],
			["Revoking", "Assigned", "Revoked"],
		)
		self.assertEqual(enqueue.call_args.kwargs["name"], ready.name)

	def key(self, status: str, **values) -> AITrialKey:
		key = frappe.get_doc(
			{
				"doctype": "AI Trial Key",
				"grove_key": frappe.generate_hash(length=8),
				"product": "raven",
				"api_key": "secret",
			}
		).insert()
		key.db_set({"status": status, **values}, update_modified=False)
		return key
