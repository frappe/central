# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.services.doctype.ai_trial_key import ai_trial_key
from central.services.doctype.ai_trial_key.ai_trial_key import TRIAL_TEAM, AITrialKey

MODULE = "central.services.doctype.ai_trial_key.ai_trial_key"
GATEWAY = "https://eu.llm.frappe.cloud"


def minted(name: str) -> dict:
	return {"name": name, "geography": "eu", "gateway_url": GATEWAY, "api_key": f"gr_{name}"}


class TestAITrialKey(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.clear_document_cache, "AI Settings", "AI Settings")
		# A revoke commits so the record outlives a failed job; tests roll back instead.
		self.enterContext(patch.object(frappe.db, "commit"))
		# A live run leaves real pool rows on the site; the counts here assume none.
		frappe.db.delete("AI Trial Key")
		self.grove = self.enterContext(patch(f"{MODULE}.GroveClient")).from_settings.return_value
		self.grove.provision_key.side_effect = lambda **kwargs: minted(frappe.generate_hash(length=10))
		self.configure(size=3)

	def configure(self, size: int, enrolled: bool = True) -> None:
		values = {
			"base_url": "https://grove.example.test" if enrolled else "",
			"control_api_key": "control" if enrolled else "",
			"trial_key_geography": "eu",
			"trial_pool_size": size,
			"trial_key_expiry": "7 Days",
			"trial_key_cap": 2,
		}
		for fieldname, value in values.items():
			frappe.db.set_single_value("AI Settings", fieldname, value)
		frappe.clear_document_cache("AI Settings", "AI Settings")

	def available(self) -> AITrialKey:
		reply = minted(frappe.generate_hash(length=10))
		return frappe.get_doc(
			{
				"doctype": "AI Trial Key",
				"grove_key": reply["name"],
				"geography": reply["geography"],
				"gateway_url": reply["gateway_url"],
				"api_key": reply["api_key"],
			}
		).insert()

	def action(self, name: str = "action-1", free: int = 1) -> Mock:
		action = Mock(team="TEAM-00001", is_free_trial=free)
		action.name = name
		return action

	def statuses(self) -> list[str]:
		return frappe.get_all("AI Trial Key", pluck="status", order_by="creation asc")

	def test_refill_mints_only_the_missing_keys_under_the_trial_team(self):
		self.available()

		ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), ["Available"] * 3)
		self.assertEqual(
			self.grove.provision_key.call_args.kwargs,
			{
				"team": TRIAL_TEAM,
				"title": None,
				"geography": "eu",
				"cap": 2,
				"expiry": "7 Days",
				"expiry_from_first_use": True,
			},
		)
		key = frappe.get_doc("AI Trial Key", frappe.get_all("AI Trial Key", pluck="name")[-1])
		self.assertEqual((key.gateway_url, key.get_password("api_key")), (GATEWAY, f"gr_{key.grove_key}"))

	def test_refill_mints_at_most_one_batch(self):
		self.configure(size=5)

		with patch(f"{MODULE}.REFILL_BATCH_SIZE", 2):
			ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), ["Available"] * 2)

	def test_a_failed_mint_stops_the_batch(self):
		self.grove.provision_key.side_effect = Exception("Grove is down")

		with patch(f"{MODULE}.frappe.log_error") as log_error:
			ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), [])
		log_error.assert_called_once()

	def test_refill_does_nothing_while_the_pool_is_off_or_central_is_not_enrolled(self):
		self.configure(size=0)
		ai_trial_key.refill_trial_keys()
		self.configure(size=3, enrolled=False)
		ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), [])
		self.grove.provision_key.assert_not_called()

	def test_a_free_trial_takes_the_oldest_key_and_a_retry_gets_the_same_one(self):
		first, second = self.available(), self.available()

		taken = AITrialKey.assign(self.action())
		retried = AITrialKey.assign(self.action())
		other = AITrialKey.assign(self.action("action-2"))

		self.assertEqual((taken.name, retried.name, other.name), (first.name, first.name, second.name))
		self.assertEqual((first.reload().status, first.team, first.resource_action), ("Assigned", "TEAM-00001", "action-1"))

	def test_a_paid_creation_and_an_empty_pool_get_no_key(self):
		self.available()

		self.assertIsNone(AITrialKey.assign(self.action(free=0)))
		AITrialKey.assign(self.action())
		self.assertIsNone(AITrialKey.assign(self.action("action-2")))

	def test_the_site_config_carries_the_key_as_pilot_writes_a_teams_own(self):
		key = self.available()

		self.assertEqual(
			key.get_site_config(),
			{
				"ai_keys": [
					{
						"name": key.grove_key,
						"title": None,
						"geography": "eu",
						"gateway_url": GATEWAY,
						"api_key": f"gr_{key.grove_key}",
					}
				]
			},
		)

	def test_a_failed_creation_releases_its_key_and_a_retry_gets_a_new_one(self):
		first, second = self.available(), self.available()
		AITrialKey.assign(self.action())

		with patch(f"{MODULE}.frappe.enqueue") as enqueue:
			AITrialKey.queue_revoke(resource_action="action-1", server=("is", "not set"))
		retried = AITrialKey.assign(self.action())

		self.assertEqual((first.reload().status, retried.name), ("Revoking", second.name))
		ai_trial_key.revoke_trial_key(enqueue.call_args.kwargs["name"])
		self.grove.revoke_key.assert_called_once_with(TRIAL_TEAM, first.grove_key)
		self.assertEqual(first.reload().status, "Revoked")

	def test_a_terminated_server_releases_the_key_it_was_linked_to(self):
		key = self.available()
		AITrialKey.assign(self.action())
		AITrialKey.link_server("action-1", "server-1")

		with patch(f"{MODULE}.frappe.enqueue"):
			AITrialKey.queue_revoke(server="server-1")

		self.assertEqual((key.reload().server, key.status), ("server-1", "Revoking"))

	def test_a_refused_revoke_stays_revoking_and_is_tried_again_once_stale(self):
		key = self.available()
		self.grove.revoke_key.side_effect = Exception("Grove refused")
		with patch(f"{MODULE}.frappe.enqueue"):
			AITrialKey.queue_revoke(name=key.name)

		ai_trial_key.retry_revokes()
		self.grove.revoke_key.assert_not_called()

		self.age(key)
		with patch(f"{MODULE}.frappe.log_error") as log_error:
			ai_trial_key.retry_revokes()
		self.assertEqual((key.reload().status, log_error.call_count), ("Revoking", 1))
		# The failed attempt wrote the record, so the next run waits another hour.
		self.grove.revoke_key.reset_mock()
		ai_trial_key.retry_revokes()
		self.grove.revoke_key.assert_not_called()

		self.grove.revoke_key.side_effect = None
		self.age(key)
		ai_trial_key.retry_revokes()
		self.assertEqual(key.reload().status, "Revoked")

	def test_only_a_revoked_record_can_be_deleted(self):
		key = self.available()

		with self.assertRaisesRegex(frappe.ValidationError, "Revoke Key"):
			key.delete()
		key.db_set("status", "Revoked")
		key.delete()

	def age(self, key: AITrialKey) -> None:
		stale = add_to_date(now_datetime(), minutes=-ai_trial_key.RETRY_AFTER_MINUTES - 1)
		frappe.db.set_value("AI Trial Key", key.name, "modified", stale, update_modified=False)
