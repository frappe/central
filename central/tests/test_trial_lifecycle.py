from unittest.mock import Mock, patch

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.infrastructure.doctype.site.site import Site
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.servers import observe_server
from central.resource_actions import submit_command, validate_trial_site
from central.signups import credit, eligibility, trial
from central.tests.test_sites import SiteOnAMachine


class TrialOnAMachine(SiteOnAMachine):
	"""One machine that runs a free trial site."""

	def setUp(self):
		super().setUp()
		# The site takes its trial clock when Central records it, so the settings come first.
		self.enterContext(
			self.change_settings(
				"Central Settings", trial_days=14, trial_deletion_days=7, trial_notice_days=3
			)
		)
		ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			self.server.name,
			server=self.server.name,
			resource_type="Site",
			is_free_trial=1,
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": None}},
		)
		self.enroll()
		self.enterContext(
			patch("central.integrations.pilot.rename_admin_domain", return_value={"task_id": "task-1"})
		)
		observe_server(self.server)
		self.notices = self.enterContext(patch("central.signups.trial.queue_event"))
		self.funnel = self.enterContext(patch("central.signups.trial.capture_trial_event"))
		self.enterContext(patch.object(frappe.db, "commit"))
		self.headroom = self.enterContext(
			patch("central.billing.catalog.subscriptions.remaining_headroom", return_value=1000)
		)

	def record_site_again(self):
		frappe.db.delete("Site", {"server": self.server.name})
		Site.create_once_addressable(self.server.name)
		return self.site()

	def run_on(self, days_from_today: int):
		trial.Trial(self.site()).advance(getdate(add_days(nowdate(), days_from_today)))
		return self.site()

	def sent_events(self) -> list[str]:
		return [call.args[1] for call in self.notices.call_args_list]

	def funnel_events(self) -> list[str]:
		return [call.args[0] for call in self.funnel.call_args_list]

	def price_trial(self, rate: float) -> None:
		"""Put the trial's server on a plan at `rate` USD a month, the price its conversion charges."""
		from central.billing.tests.utils import complete_billing_profile, make_plan

		complete_billing_profile(self.team.name, currency="USD")
		plan = make_plan("trial-lifecycle-plan", rates=[{"cluster": "", "currency": "USD", "rate": rate}])
		frappe.db.set_value("Virtual Machine", self.server.name, "plan", plan)

	def trial_comments(self) -> str:
		return "\n".join(
			frappe.get_all(
				"Comment",
				filters={
					"reference_doctype": "Site",
					"reference_name": self.site().name,
					"comment_type": "Info",
				},
				pluck="content",
			)
		)


class TestTrialLifecycle(TrialOnAMachine):
	"""A trial site runs for its days, warns, stops, then is terminated."""

	def test_a_trial_refuses_a_state_its_lifecycle_does_not_allow(self):
		self.site().db_set("trial_state", "Converted")

		with self.assertRaises(trial.InvalidTrialTransition):
			trial.Trial(self.site()).move_to("Active")

	def test_a_terminated_trial_server_closes_its_trial_at_once(self):
		self.server.db_set("status", "Terminated")
		frappe.get_doc("Virtual Machine", self.server.name).close_trial()

		site = self.site()
		self.assertEqual(site.trial_state, "Deleted")
		self.assertEqual(self.sent_events(), ["trial_deleted"])
		self.assertIsNone(eligibility.get_open_trial_of_owner(self.team.name))

	def test_a_new_trial_site_gets_its_end_date_before_it_is_ready(self):
		site = self.site()

		self.assertIsNone(site.ready_at)
		self.assertEqual(site.trial_state, "Active")
		self.assertEqual(getdate(site.trial_ends_on), getdate(add_days(nowdate(), 14)))

	def test_a_product_sets_its_own_trial_length(self):
		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "raven-trial",
				"title": "Raven",
				"signup_app": "raven",
				"trial_days": 30,
			}
		).insert()

		self.assertEqual(trial.TrialSettings(product.name).days, 30)
		self.assertEqual(trial.TrialSettings(product.name).deletion_days, 7)

	def test_the_patch_starts_a_trial_site_recorded_before_trials_started_on_insert(self):
		from central.patches.v0_0 import start_unready_trials

		self.site().db_set({"trial_state": "", "trial_ends_on": None})
		start_unready_trials.execute()

		site = self.site()
		self.assertEqual(site.trial_state, "Active")
		self.assertEqual(getdate(site.trial_ends_on), getdate(add_days(nowdate(), 14)))

	def test_the_patch_leaves_a_site_from_before_trials_that_was_opened(self):
		from central.patches.v0_0 import start_unready_trials

		self.site().db_set({"trial_state": "", "trial_ends_on": None, "claimed_at": now_datetime()})
		start_unready_trials.execute()

		self.assertFalse(self.site().trial_state)

	def test_a_team_that_pays_has_no_trial(self):
		frappe.db.set_value("Resource Action", {"server": self.server.name}, "is_free_trial", 0)
		site = self.record_site_again()

		self.assertEqual(site.trial_state, "Converted")
		self.assertIsNone(site.trial_ends_on)

	def test_only_a_product_signup_gets_a_free_trial(self):
		self.assertTrue(eligibility.is_free_trial_creation(self.team.name, "raven"))
		self.assertFalse(eligibility.is_free_trial_creation(self.team.name, None))

	def test_a_team_that_has_paid_before_gets_no_free_trial(self):
		invoice = frappe.get_doc({"doctype": "Invoice", "team": self.team.name, "status": "Draft"})
		invoice.db_insert()
		self.assertTrue(eligibility.is_free_trial_creation(self.team.name, "raven"))

		invoice.db_set("status", "Overdue")
		self.assertFalse(eligibility.is_free_trial_creation(self.team.name, "raven"))

	def test_a_team_with_a_subscription_gets_no_free_trial(self):
		frappe.get_doc({"doctype": "Subscription", "team": self.team.name}).db_insert()

		self.assertFalse(eligibility.is_free_trial_creation(self.team.name, "raven"))

	def test_a_card_cancelled_before_the_site_is_recorded_keeps_the_server_paid(self):
		frappe.db.set_value("Resource Action", {"server": self.server.name}, "is_free_trial", 0)
		with patch("central.signups.trial.has_active_payment_method", return_value=False):
			site = self.record_site_again()

		self.assertEqual(site.trial_state, "Converted")
		self.assertFalse(trial.is_billing_deferred(self.server.name))

	def test_a_card_added_before_the_site_is_recorded_converts_it_on_record(self):
		self.server.db_set("status", "Running")
		with patch("central.signups.trial.has_active_payment_method", return_value=True):
			site = self.record_site_again()

		self.assertEqual(site.trial_state, "Converted")
		self.assertEqual(self.sent_events(), ["trial_converted"])
		self.assert_conversion_queued()

	def test_the_patch_marks_creations_that_started_a_trial(self):
		from central.patches.v0_0 import set_free_trial_on_creations

		frappe.db.set_value("Resource Action", {"server": self.server.name}, "is_free_trial", 0)
		set_free_trial_on_creations.execute()

		self.assertEqual(
			frappe.db.get_value("Resource Action", {"server": self.server.name}, "is_free_trial"), 1
		)

	def test_the_patch_marks_a_pending_creation_that_has_no_server_yet(self):
		from central.patches.v0_0 import set_free_trial_on_creations

		pending = ResourceAction.queue(
			"create",
			self.team.name,
			self.region.name,
			"pending-" + frappe.generate_hash(length=8),
			resource_type="Site",
			request_key="request-" + frappe.generate_hash(length=8),
			request_payload={"image_tags": {"purpose": "pilot"}, "site": {"product": None}},
		)
		set_free_trial_on_creations.execute()

		self.assertEqual(frappe.db.get_value("Resource Action", pending.name, "is_free_trial"), 1)

	def test_a_site_that_is_not_a_trial_has_no_trial_state(self):
		frappe.db.delete("Resource Action", {"server": self.server.name})

		self.assertFalse(self.record_site_again().trial_state)

	def test_warnings_go_out_three_days_and_one_day_before_the_end_once_each(self):
		for days in (11, 12, 13, 13):
			self.run_on(days)

		self.assertEqual(self.sent_events(), ["trial_expiring", "trial_expiring"])
		self.assertEqual(self.site().trial_last_notice, "last day")

	def test_a_ready_site_that_nobody_opened_gets_one_reminder_the_next_day(self):
		self.site().db_set("ready_at", now_datetime())
		self.run_on(0)
		self.run_on(1)
		self.run_on(2)

		self.assertEqual(self.sent_events(), ["trial_unopened"])

	def test_an_opened_site_gets_no_reminder(self):
		self.site().db_set({"ready_at": now_datetime(), "claimed_at": now_datetime()})
		self.run_on(1)

		self.assertEqual(self.sent_events(), [])

	def test_the_end_date_stops_the_server_and_sets_the_deletion_date(self):
		with patch.object(trial.Trial, "enqueue_job") as enqueue_job:
			site = self.run_on(14)

		self.assertEqual(site.trial_state, "Ended")
		self.assertEqual(getdate(site.trial_deletes_on), getdate(add_days(nowdate(), 21)))
		enqueue_job.assert_called_once_with(trial.stop_server, "trial-stop")
		self.assertEqual(self.sent_events(), [])
		self.assertEqual(self.funnel_events(), ["trial_ended"])

	def test_the_team_hears_the_trial_ended_once_the_server_is_stopped(self):
		self.site().db_set("trial_state", "Ended")
		with patch("central.integrations.servers.hold_server_stopped"):
			trial.stop_server(self.site().name)

		self.assertEqual(self.sent_events(), ["trial_ended"])

	def test_the_deletion_date_terminates_the_server_and_deletes_the_site_once_it_is_gone(self):
		self.site().db_set({"trial_state": "Ended", "trial_deletes_on": nowdate()})

		site = self.run_on(0)

		self.assertEqual(site.trial_state, "Ended")
		action = frappe.get_last_doc("Resource Action", {"server": self.server.name, "action": "terminate"})
		self.assertEqual(action.requested_by, "Administrator")
		self.assertEqual(self.sent_events(), [])

		frappe.db.set_value("Virtual Machine", self.server.name, "status", "Terminated")
		site = self.run_on(0)

		self.assertEqual(site.trial_state, "Deleted")
		self.assertEqual(self.sent_events(), ["trial_deleted"])
		self.assertEqual(self.funnel_events(), ["trial_deleted"])

	def test_a_refused_termination_stays_selectable_and_is_asked_again(self):
		self.site().db_set({"trial_state": "Ended", "trial_deletes_on": nowdate()})
		self.run_on(0)
		frappe.db.set_value(
			"Resource Action",
			{"server": self.server.name, "action": "terminate"},
			"status",
			"Failed",
		)

		site = self.run_on(0)

		self.assertEqual(site.trial_state, "Ended")
		self.assertIn("did not terminate", site.trial_error)
		self.assertEqual(
			frappe.db.count("Resource Action", {"server": self.server.name, "action": "terminate"}), 2
		)

	def test_a_protected_trial_server_is_kept_with_the_reason(self):
		self.site().db_set({"trial_state": "Ended", "trial_deletes_on": nowdate()})
		frappe.db.set_value("Virtual Machine", self.server.name, "is_termination_protected", 1)

		site = self.run_on(0)

		self.assertEqual(site.trial_state, "Ended")
		self.assertIn("Termination protection is on", site.trial_error)
		self.assertFalse(
			frappe.db.exists("Resource Action", {"server": self.server.name, "action": "terminate"})
		)

	def test_a_failed_stop_leaves_the_reason_on_the_site(self):
		self.site().db_set("trial_state", "Ended")
		with (
			patch("central.integrations.servers.hold_server_stopped", side_effect=RuntimeError("down")),
			patch.object(frappe.db, "rollback"),
		):
			trial.stop_server(self.site().name)

		self.assertIn("could not stop", self.site().trial_error)
		self.assertEqual(self.sent_events(), [])

	def test_a_converted_trial_is_not_stopped(self):
		self.site().db_set("trial_state", "Converted")
		with patch("central.integrations.servers.hold_server_stopped") as hold_server_stopped:
			trial.stop_server(self.site().name)

		hold_server_stopped.assert_not_called()

	def test_a_trial_server_has_no_subscription_until_it_converts(self):
		self.assertTrue(trial.is_billing_deferred(self.server.name))

		self.site().db_set("trial_state", "Converted")
		self.assertFalse(trial.is_billing_deferred(self.server.name))

	def test_a_bought_server_is_billed_at_once(self):
		frappe.db.set_value(
			"Resource Action",
			{"server": self.server.name},
			{
				"resource_type": "Server",
				"is_free_trial": 0,
				"request_payload": '{"image_tags": {"purpose": "pilot"}}',
			},
		)
		self.record_site_again()

		self.assertFalse(trial.is_billing_deferred(self.server.name))

	def test_an_active_payment_method_converts_the_team_trials(self):
		self.price_trial(30)
		frappe.db.set_value(
			"Site", self.site().name, "creation", add_days(now_datetime(), -3), update_modified=False
		)
		self.server.db_set("status", "Running")
		method = Mock(team=self.team.name, status="Active")
		method.get_doc_before_save.return_value = Mock(status="Pending Validation")

		with patch("central.signups.credit.grant_welcome_credits"):
			credit.on_payment_method_update(method)

		site = self.site()
		self.assertEqual(site.trial_state, "Converted")
		self.assertAlmostEqual(site.trial_cost, 3, places=1)
		self.funnel.assert_called_once_with("trial_converted", self.team.name, None, days_in_trial=3)
		self.assertEqual(self.sent_events(), ["trial_converted"])
		VirtualMachine.ensure_subscription_enabled.assert_called()
		self.assert_conversion_queued()

	def test_a_trial_above_the_spending_limit_stays_a_trial_until_the_limit_is_raised(self):
		self.price_trial(30)
		self.headroom.return_value = 20
		with patch("central.signups.trial.has_active_payment_method", return_value=True):
			trial.convert_team(self.team.name)

			site = self.site()
			self.assertEqual(site.trial_state, "Active")
			self.assertIn("spending limit", site.trial_error)
			self.assertTrue(trial.get_trial_status(self.server.name)["held"])

			self.headroom.return_value = 30
			site = self.run_on(1)

		self.assertEqual(site.trial_state, "Converted")
		self.assertFalse(site.trial_error)

	def test_a_converted_server_that_is_still_starting_holds_its_rate(self):
		self.price_trial(30)
		self.site().db_set("trial_state", "Converted")

		self.assertEqual(trial.get_starting_rate(self.team.name), 30)

	def test_a_terminated_server_from_a_failed_conversion_holds_no_rate(self):
		self.price_trial(30)
		self.site().db_set({"trial_state": "Converted", "trial_error": "Could not start"})
		self.server.db_set("status", "Terminated")

		self.assertEqual(trial.get_starting_rate(self.team.name), 0)

	def test_a_trial_waits_while_another_conversion_uses_the_limit(self):
		self.price_trial(30)
		self.headroom.return_value = 40
		with patch("central.signups.trial.get_starting_rate", return_value=20):
			self.assertFalse(trial.Trial(self.site()).convert_within_limit())

		self.assertEqual(self.site().trial_state, "Active")

	def test_an_ended_trial_above_the_spending_limit_cannot_be_kept(self):
		self.price_trial(30)
		self.headroom.return_value = 0
		self.site().db_set("trial_state", "Ended")
		with (
			patch("central.signups.trial.has_active_payment_method", return_value=True),
			self.assertRaisesRegex(frappe.ValidationError, "spending limit"),
		):
			trial.Trial(self.site()).keep()

	def test_a_payment_method_leaves_an_ended_trial_stopped(self):
		self.site().db_set("trial_state", "Ended")
		method = Mock(team=self.team.name, status="Active")
		method.get_doc_before_save.return_value = Mock(status="Pending Validation")

		with patch("central.signups.credit.grant_welcome_credits"):
			credit.on_payment_method_update(method)

		self.assertEqual(self.site().trial_state, "Ended")
		with patch("central.signups.trial.has_active_payment_method", return_value=True):
			self.assertTrue(trial.get_trial_status(self.server.name)["can_keep"])

	def test_keeping_an_ended_trial_converts_it_and_starts_its_server(self):
		from central.api.servers import keep_trial_site

		self.site().db_set("trial_state", "Ended")
		with patch("central.signups.trial.has_active_payment_method", return_value=True):
			keep_trial_site(self.team.name, self.server.resource_id)

		self.assertEqual(self.site().trial_state, "Converted")
		self.assert_conversion_queued()

	def test_an_ended_trial_is_kept_only_with_a_payment_method(self):
		from central.api.servers import keep_trial_site

		self.site().db_set("trial_state", "Ended")
		self.assertFalse(trial.get_trial_status(self.server.name)["can_keep"])
		with self.assertRaisesRegex(frappe.ValidationError, "Add a payment method"):
			keep_trial_site(self.team.name, self.server.resource_id)

		self.assertEqual(self.site().trial_state, "Ended")

	def test_only_a_billing_manager_keeps_a_trial(self):
		from central.api.servers import keep_trial_site

		self.site().db_set("trial_state", "Ended")
		with self.set_user("Guest"), self.assertRaises(frappe.PermissionError):
			keep_trial_site(self.team.name, self.server.resource_id)

	def test_only_a_billing_manager_is_offered_to_keep_a_trial(self):
		self.site().db_set("trial_state", "Ended")
		with (
			patch("central.signups.trial.has_active_payment_method", return_value=True),
			self.set_user("Guest"),
		):
			self.assertFalse(trial.get_trial_status(self.server.name)["can_keep"])

	def test_a_sleeping_server_is_subscribed_when_its_trial_converts(self):
		self.server.db_set("status", "Paused")
		VirtualMachine.ensure_subscription_enabled.reset_mock()

		trial.Trial(self.site()).convert()

		VirtualMachine.ensure_subscription_enabled.assert_called_once()

	def test_resize_options_say_a_converted_server_is_still_starting(self):
		from central.billing.api.dashboard.catalog import get_composed_config

		self.site().db_set("trial_state", "Converted")

		config = get_composed_config(self.server.name, self.team.name)

		self.assertTrue(config["starting"])
		self.assertIsNone(config["trial"])

	def assert_conversion_queued(self):
		frappe.enqueue.assert_any_call(
			trial.finish_conversion,
			site=self.site().name,
			queue="long",
			enqueue_after_commit=True,
			job_id=f"trial-convert:{self.site().name}",
			deduplicate=True,
		)

	def test_a_converted_server_that_the_trial_stopped_starts_again(self):
		self.site().db_set("trial_state", "Converted")
		self.server.db_set("status", "Stopped")
		with patch("central.integrations.servers.convert_trial_server") as convert_trial_server:
			trial.finish_conversion(self.site().name)

		convert_trial_server.assert_called_once_with(self.server.name, start=True)

	def test_the_in_app_trial_status_carries_its_contract_fields(self):
		"""The site's billing tab reads these fields; their names are the contract with Pilot."""
		self.price_trial(40)
		frappe.db.set_value("Resource Action", {"server": self.server.name}, "reserved_monthly_rate", 30)
		status = trial.get_trial_status(self.server.name)

		self.assertEqual(
			set(status),
			{
				"state",
				"can_keep",
				"held",
				"ends_on",
				"days_left",
				"deletes_on",
				"plan",
			},
		)
		# The reserved rate is older than the catalog; the subscription charges the catalog rate.
		self.assertEqual(
			status["plan"], {"title": "trial-lifecycle-plan", "monthly_rate": 40, "currency": "USD"}
		)

	def test_resize_options_say_the_trial_blocks_a_resize(self):
		from central.billing.api.dashboard.catalog import get_composed_config

		config = get_composed_config(self.server.name, self.team.name)

		self.assertFalse(config["resizable"])
		self.assertEqual(config["trial"]["state"], "Active")

	def test_a_pending_action_defers_the_conversion_to_the_daily_job(self):
		"""Any pending action on the server, not only a resize, defers it with a reason to retry."""
		self.site().db_set("trial_state", "Converted")
		for action in ("resize", "restart"):
			pending = ResourceAction.queue(
				action, self.team.name, self.region.name, "pending", server=self.server.name
			)
			with patch("central.integrations.servers.convert_trial_server") as convert_trial_server:
				trial.finish_conversion(self.site().name)

			convert_trial_server.assert_not_called()
			self.assertIn("Another action is running", self.site().trial_error)
			pending.db_set("status", "Succeeded")

	def test_a_failed_conversion_leaves_the_reason_and_the_daily_job_retries_it(self):
		self.site().db_set("trial_state", "Converted")
		with (
			patch("central.integrations.servers.convert_trial_server", side_effect=RuntimeError("down")),
			patch.object(frappe.db, "rollback"),
		):
			trial.finish_conversion(self.site().name)

		self.assertIn("could not start", self.site().trial_error)

		frappe.enqueue.reset_mock()
		trial.run_trials()
		self.assert_conversion_queued()

	def test_a_team_that_pays_during_the_stop_gets_its_server_back(self):
		self.site().db_set("trial_state", "Ended")

		def pay_during_stop(server):
			self.site().db_set("trial_state", "Converted")

		with patch("central.integrations.servers.hold_server_stopped", side_effect=pay_during_stop):
			trial.stop_server(self.site().name)

		self.assert_conversion_queued()
		self.assertEqual(self.sent_events(), [])

	def test_an_ended_trial_cannot_be_started(self):
		self.site().db_set("trial_state", "Ended")

		with self.assertRaisesRegex(frappe.ValidationError, "Add a payment method"):
			submit_command("start", self.team.name, self.server.name)
		with (
			patch("central.resource_actions.has_active_payment_method", return_value=True),
			self.assertRaisesRegex(frappe.ValidationError, "Keep this site"),
		):
			submit_command("start", self.team.name, self.server.name)

	def test_a_team_has_a_limited_number_of_free_trial_sites(self):
		with self.change_settings("Central Settings", trial_servers_per_team=1):
			with self.assertRaisesRegex(frappe.ValidationError, f"trial at {self.site().name} is still open"):
				validate_trial_site(self.team.name)

	def test_an_owner_gets_no_new_trials_by_making_another_team(self):
		owner = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"owner-{frappe.generate_hash(length=8)}@example.test",
				"first_name": "Owner",
			}
		).insert()
		self.team.db_set("owner_user", owner.name)
		other = frappe.get_doc({"doctype": "Team", "team_name": "Second", "owner_user": owner.name}).insert()

		with self.change_settings("Central Settings", trial_servers_per_team=1):
			with self.assertRaisesRegex(frappe.ValidationError, "is still open"):
				validate_trial_site(other.name)

			self.site().db_set("trial_state", "Deleted")
			validate_trial_site(other.name)

	def test_a_server_whose_site_is_not_recorded_yet_still_counts_toward_the_limit(self):
		frappe.db.delete("Site", {"server": self.server.name})

		with self.change_settings("Central Settings", trial_servers_per_team=1):
			with self.assertRaisesRegex(frappe.ValidationError, "still being set up"):
				validate_trial_site(self.team.name)

	def test_the_billing_panel_reads_the_open_trial_of_the_server(self):
		status = trial.get_trial_status(self.server.name)
		self.assertEqual(status["state"], "Active")
		self.assertEqual(status["days_left"], 14)
		self.assertIsNone(trial.get_trial_status(self.server.name, site="other.example.test"))

		self.site().db_set("trial_state", "Converted")
		self.assertIsNone(trial.get_trial_status(self.server.name))

	def test_an_operator_extends_an_ended_trial_and_its_server_starts(self):
		self.site().db_set(
			{"trial_state": "Ended", "trial_ends_on": nowdate(), "trial_deletes_on": nowdate()}
		)

		self.site().extend_trial(7)

		site = self.site()
		self.assertEqual(site.trial_state, "Active")
		self.assertEqual(getdate(site.trial_ends_on), getdate(add_days(nowdate(), 7)))
		self.assertIsNone(site.trial_deletes_on)
		self.assertTrue(frappe.db.exists("Resource Action", {"server": self.server.name, "action": "start"}))

	def test_an_operator_ends_an_active_trial_now(self):
		with patch.object(trial.Trial, "enqueue_job"):
			self.site().end_trial_now()

		self.assertEqual(self.site().trial_state, "Ended")

	def test_ending_a_trial_revokes_its_ai_key(self):
		with (
			patch.object(trial.Trial, "enqueue_job"),
			patch.object(trial.AITrialKey, "queue_revoke") as revoke,
		):
			self.site().end_trial_now()

		revoke.assert_called_once_with(server=self.server.name)

	def test_converting_a_trial_hands_its_ai_key_to_the_team_and_notes_a_trial_without_one(self):
		with (
			patch.object(trial.Trial, "enqueue_job"),
			patch.object(trial.AITrialKey, "queue_convert", return_value=True) as convert,
		):
			trial.Trial(self.site()).convert()
		convert.assert_called_once_with(self.server.name)
		self.assertNotIn("AI key", self.trial_comments())

		self.site().db_set("trial_state", "Active")
		with (
			patch.object(trial.Trial, "enqueue_job"),
			patch.object(trial.AITrialKey, "queue_convert", return_value=False),
		):
			trial.Trial(self.site()).convert()
		self.assertIn("no live AI key to hand over", self.trial_comments())

	def test_extending_an_ended_trial_without_a_live_ai_key_says_so_and_an_active_one_says_nothing(self):
		self.site().extend_trial(3)
		self.assertNotIn("AI key", self.trial_comments())

		self.site().db_set(
			{"trial_state": "Ended", "trial_ends_on": nowdate(), "trial_deletes_on": nowdate()}
		)
		self.site().extend_trial(2)
		self.assertIn("had no AI key", self.trial_comments())

		frappe.get_doc(
			{"doctype": "AI Trial Key", "grove_key": "ended-key", "status": "Revoked", "server": self.server.name}
		).insert()
		self.site().db_set({"trial_state": "Ended", "trial_deletes_on": nowdate()})
		self.site().extend_trial(2)
		self.assertIn("revoked when it ended", self.trial_comments())

	def test_only_an_operator_changes_a_trial(self):
		with self.set_user("Guest"), self.assertRaises(frappe.PermissionError):
			self.site().extend_trial(7)
