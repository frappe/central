from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.services.doctype.ai_trial_key.ai_trial_key import AITrialKey, refill_trial_keys

TRIAL_KEYS = "central.services.doctype.ai_trial_key.ai_trial_key"


class TestAITrialKeyPause(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.db.rollback)
		frappe.db.set_single_value(
			"AI Settings",
			{"base_url": "https://grove.test", "control_api_key": "control", "trial_pool_size": 1},
		)

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
		key = frappe.get_doc({"doctype": "AI Trial Key", "grove_key": "key-1", "api_key": "secret"}).insert()
		frappe.db.set_single_value("AI Settings", "pause_key_assignment", 1)
		action = Mock(is_free_trial=1, team="TEAM-00001")
		action.name = "action-1"

		self.assertIsNone(AITrialKey.assign(action))
		self.assertEqual(frappe.db.get_value("AI Trial Key", key.name, "status"), "Available")
