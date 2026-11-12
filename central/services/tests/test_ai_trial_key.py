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
	return {"name": name, "geography": "eu", "gateway_url": GATEWAY, "cap": 2, "api_key": f"gr_{name}"}


def product(key: str) -> str:
	if not frappe.db.exists("Product", key):
		frappe.get_doc({"doctype": "Product", "product_key": key, "title": key, "signup_app": key}).insert()
	return key


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
		self.configure(products={"raven": 3})

	def configure(
		self,
		products: dict[str, int],
		enrolled: bool = True,
		groups: dict | None = None,
		revoke_after_days: int = 30,
	) -> None:
		"""The Trials tab: one pool row per product in `products` ({key: size}), each in the Model
		Group `groups` names for it, if any."""
		settings = frappe.get_doc("AI Settings")
		settings.update(
			{
				"base_url": "https://grove.example.test" if enrolled else "",
				"control_api_key": "control" if enrolled else "",
				"control_api_secret": "secret" if enrolled else "",
				"trial_key_geography": "eu",
				"trial_key_cap": 2,
				"trial_key_revoke_after_days": revoke_after_days,
				"trial_products": [
					{"product": product(key), "pool_size": size, "model_group": (groups or {}).get(key)}
					for key, size in products.items()
				],
			}
		)
		settings.save()
		frappe.clear_document_cache("AI Settings", "AI Settings")

	def available(self, product_key: str = "raven") -> AITrialKey:
		reply = minted(frappe.generate_hash(length=10))
		return frappe.get_doc(
			{
				"doctype": "AI Trial Key",
				"grove_key": reply["name"],
				"product": product(product_key),
				"geography": reply["geography"],
				"gateway_url": reply["gateway_url"],
				"cap": reply["cap"],
				"api_key": reply["api_key"],
			}
		).insert()

	def action(self, name: str = "action-1", free: int = 1, product_key: str = "raven") -> Mock:
		action = Mock(team="TEAM-00001", is_free_trial=free, product=product_key)
		action.name = name
		return action

	def statuses(self) -> list[str]:
		return frappe.get_all("AI Trial Key", pluck="status", order_by="creation asc")

	def test_refill_mints_only_the_missing_keys_under_the_trial_team(self):
		self.available()

		ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), ["Available"] * 3)
		key = frappe.get_doc(
			"AI Trial Key", frappe.get_all("AI Trial Key", pluck="name", order_by="creation asc")[-1]
		)
		# The record has an id of its own, and that id is the key's title at Grove.
		self.assertTrue(key.name.startswith("AITK-") and key.name != key.grove_key)
		self.assertEqual(
			self.grove.provision_key.call_args.kwargs,
			{
				"team": TRIAL_TEAM,
				"title": key.name,
				"geography": "eu",
				"cap": 2,
				"model_groups": None,
			},
		)
		self.assertEqual((key.gateway_url, key.get_password("api_key")), (GATEWAY, f"gr_{key.grove_key}"))
		self.assertEqual(key.product, "raven")

	def test_each_product_is_refilled_to_its_size_in_its_group_within_one_batch(self):
		self.configure(products={"raven": 2, "crm": 2}, groups={"crm": "crm-trial"})
		self.available()

		with patch(f"{MODULE}.REFILL_BATCH_SIZE", 2):
			ai_trial_key.refill_trial_keys()

		self.assertEqual(
			frappe.get_all("AI Trial Key", pluck="product", order_by="creation asc"),
			["raven", "raven", "crm"],
		)
		sent = [call.kwargs["model_groups"] for call in self.grove.provision_key.call_args_list]
		self.assertEqual(sent, [None, ["crm-trial"]])

	def test_one_pool_row_per_product(self):
		settings = frappe.get_doc("AI Settings")
		settings.append("trial_products", {"product": "raven", "pool_size": 1})
		with self.assertRaisesRegex(frappe.ValidationError, "One pool row per product"):
			settings.save()

	def test_refill_mints_at_most_one_batch(self):
		self.configure(products={"raven": 5})

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
		self.configure(products={"raven": 0})
		ai_trial_key.refill_trial_keys()
		self.configure(products={"raven": 3}, enrolled=False)
		ai_trial_key.refill_trial_keys()

		self.assertEqual(self.statuses(), [])
		self.grove.provision_key.assert_not_called()

	def test_a_pending_revoke_is_retried_with_the_pool_off(self):
		key = self.available()
		with patch(f"{MODULE}.frappe.enqueue"):
			AITrialKey.queue_revoke(name=key.name)
		self.age(key)
		self.configure(products={"raven": 0})

		ai_trial_key.refill_trial_keys()

		self.assertEqual(key.reload().status, "Revoked")
		self.grove.provision_key.assert_not_called()

	def test_a_free_trial_takes_the_oldest_key_and_a_retry_gets_the_same_one(self):
		first, second = self.available(), self.available()

		taken = AITrialKey.assign(self.action())
		retried = AITrialKey.assign(self.action())
		other = AITrialKey.assign(self.action("action-2"))

		self.assertEqual((taken.name, retried.name, other.name), (first.name, first.name, second.name))
		self.assertEqual(
			(first.reload().status, first.team, first.resource_action), ("Assigned", "TEAM-00001", "action-1")
		)

	def test_a_free_trial_takes_a_key_of_its_product_and_none_of_anothers(self):
		crm, raven = self.available("crm"), self.available("raven")

		self.assertEqual(AITrialKey.assign(self.action()).name, raven.name)
		self.assertIsNone(AITrialKey.assign(self.action("action-2")))
		self.assertEqual(AITrialKey.assign(self.action("action-3", product_key="crm")).name, crm.name)

	def test_only_a_running_trials_cap_can_be_raised_and_only_upward(self):
		key = self.available()
		with self.assertRaisesRegex(frappe.ValidationError, "running trial"):
			key.raise_cap(5)

		AITrialKey.assign(self.action())
		key.reload().raise_cap(5)
		self.grove.update_caps.assert_called_once_with(TRIAL_TEAM, {key.grove_key: 5})
		self.assertEqual(key.reload().cap, 5)
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			key.raise_cap(5)

		# A key on its way to the team, or out, is nobody's to raise here.
		for status in ("Converting", "Converted", "Conversion Failed", "Revoking", "Revoked"):
			key.db_set("status", status)
			with self.assertRaisesRegex(frappe.ValidationError, "running trial"):
				key.reload().raise_cap(9)
		self.grove.update_caps.assert_called_once()

	def test_a_paid_creation_and_an_empty_pool_get_no_key(self):
		self.available()

		self.assertIsNone(AITrialKey.assign(self.action(free=0)))
		AITrialKey.assign(self.action())
		self.assertIsNone(AITrialKey.assign(self.action("action-2")))

	def test_the_site_config_carries_the_key_as_pilot_writes_a_teams_own(self):
		key = self.available()

		self.assertEqual(
			key.get_site_config(),
			{"ai_keys": [{"gateway_url": GATEWAY, "api_key": f"gr_{key.grove_key}"}]},
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

	def test_an_assigned_key_is_revoked_once_its_days_have_passed(self):
		self.configure(products={"raven": 0})
		aged, fresh = self.available(), self.available()
		self.available()
		AITrialKey.assign(self.action())
		AITrialKey.assign(self.action("action-2"))

		self.age_assignment(aged)
		with patch(f"{MODULE}.frappe.enqueue"):
			ai_trial_key.refill_trial_keys()
		self.assertEqual(self.statuses(), ["Revoking", "Assigned", "Available"])

		# 0 turns the stop off.
		self.configure(products={"raven": 0}, revoke_after_days=0)
		self.age_assignment(fresh)
		with patch(f"{MODULE}.frappe.enqueue"):
			ai_trial_key.refill_trial_keys()
		self.assertEqual(self.statuses(), ["Revoking", "Assigned", "Available"])

	def test_a_refused_revoke_stays_revoking_and_is_tried_again_once_stale(self):
		key = self.available()
		self.grove.revoke_key.side_effect = Exception("Grove refused")
		with patch(f"{MODULE}.frappe.enqueue"):
			AITrialKey.queue_revoke(name=key.name)
		# The queued job itself: the refusal lands on the record, nothing raises.
		with patch(f"{MODULE}.frappe.log_error"):
			ai_trial_key.revoke_trial_key(key.name)
		self.assertEqual((key.reload().status, key.last_error), ("Revoking", "Grove refused"))
		self.grove.revoke_key.reset_mock()

		ai_trial_key.retry_stale()
		self.grove.revoke_key.assert_not_called()

		self.age(key)
		with patch(f"{MODULE}.frappe.log_error") as log_error:
			ai_trial_key.retry_stale()
		self.assertEqual((key.reload().status, log_error.call_count), ("Revoking", 1))
		self.assertEqual(key.last_error, "Grove refused")
		# The failed attempt wrote the record, so the next run waits another hour.
		self.grove.revoke_key.reset_mock()
		ai_trial_key.retry_stale()
		self.grove.revoke_key.assert_not_called()

		self.grove.revoke_key.side_effect = None
		self.age(key)
		ai_trial_key.retry_stale()
		self.assertEqual((key.reload().status, key.last_error), ("Revoked", None))

	def test_only_a_revoked_record_can_be_deleted(self):
		key = self.available()

		with self.assertRaisesRegex(frappe.ValidationError, "Revoke Key"):
			key.delete()
		key.db_set("status", "Revoked")
		key.delete()

	def age(self, key: AITrialKey) -> None:
		stale = add_to_date(now_datetime(), minutes=-ai_trial_key.RETRY_AFTER_MINUTES - 1)
		frappe.db.set_value("AI Trial Key", key.name, "modified", stale, update_modified=False)

	def age_assignment(self, key: AITrialKey) -> None:
		expired = add_to_date(now_datetime(), days=-31)
		frappe.db.set_value("AI Trial Key", key.name, "assigned_at", expired)

	def converting(self) -> tuple[AITrialKey, str]:
		"""An assigned key whose trial converted, its hand-over queued: the record and the job's name."""
		key = self.available()
		AITrialKey.assign(self.action())
		AITrialKey.link_server("action-1", "server-1")
		with patch(f"{MODULE}.frappe.enqueue") as enqueue:
			self.assertTrue(AITrialKey.queue_convert("server-1"))
		return key, enqueue.call_args.kwargs["name"]

	def handing_over(self):
		"""The converted site the hand-over reads, and AI's enable, both out of this test's reach."""
		site = frappe._dict(name="trial.example.test", team="TEAM-00001")
		converted = patch.object(AITrialKey, "converted_site", return_value=site)
		return converted, patch("central.services.ai.enable")

	def test_a_converted_trial_hands_its_key_to_the_team_titled_by_the_site(self):
		key, name = self.converting()
		self.assertEqual(key.reload().status, "Converting")
		self.assertFalse(AITrialKey.queue_convert("server-1"))

		site, enable = self.handing_over()
		with site, enable as enable:
			ai_trial_key.convert_trial_key(name)

		enable.assert_called_once_with("TEAM-00001")
		self.grove.transfer_key.assert_called_once_with(
			TRIAL_TEAM, key.grove_key, "TEAM-00001", "trial.example.test"
		)
		self.assertEqual((key.reload().status, key.team), ("Converted", "TEAM-00001"))
		# The team's now: its server's termination takes nothing.
		with patch(f"{MODULE}.frappe.enqueue"):
			AITrialKey.queue_revoke(server="server-1")
		self.assertEqual(key.reload().status, "Converted")

	def test_a_refused_hand_over_is_tried_hourly_and_given_up_after_three_then_the_key_is_revoked(self):
		key, name = self.converting()
		self.grove.transfer_key.side_effect = Exception("Grove is down")
		site, enable = self.handing_over()
		with site, enable, patch(f"{MODULE}.frappe.log_error") as log_error:
			ai_trial_key.convert_trial_key(name)
			key.reload()
			self.assertEqual((key.status, key.attempts, key.last_error), ("Converting", 1, "Grove is down"))
			ai_trial_key.retry_stale()
			self.assertEqual(key.reload().attempts, 1)
			self.age(key)
			ai_trial_key.retry_stale()
			self.assertEqual((key.reload().status, key.attempts), ("Converting", 2))
			self.age(key)
			with patch(f"{MODULE}.frappe.enqueue") as enqueue:
				ai_trial_key.retry_stale()
		self.assertEqual((key.reload().status, key.attempts, key.revoked), ("Conversion Failed", 3, 0))
		self.assertEqual((log_error.call_count, key.last_error), (3, "Grove is down"))
		# The failure queues the revoke; a refused one keeps Grove's answer and waits its hour; the
		# status keeps the failure.
		self.grove.revoke_key.side_effect = Exception("Grove is still down")
		with patch(f"{MODULE}.frappe.log_error"):
			ai_trial_key.revoke_trial_key(enqueue.call_args.kwargs["name"])
		self.assertEqual(
			(key.reload().status, key.revoked, key.last_error),
			("Conversion Failed", 0, "Grove is still down"),
		)
		self.grove.revoke_key.side_effect = None
		ai_trial_key.retry_stale()
		self.assertEqual(key.reload().revoked, 0)
		self.age(key)
		ai_trial_key.retry_stale()
		self.grove.revoke_key.assert_called_with(TRIAL_TEAM, key.grove_key)
		self.assertEqual((key.reload().status, key.revoked, key.last_error), ("Conversion Failed", 1, None))
		self.age(key)
		self.grove.revoke_key.reset_mock()
		ai_trial_key.retry_stale()
		self.grove.revoke_key.assert_not_called()
		key.reload().delete()
