from unittest.mock import Mock, patch

import frappe
import requests

from central.api.sites import get_open_trial, get_trial_app_install, install_trial_app
from central.tests.test_team_management import create_user
from central.tests.test_trial_lifecycle import TrialOnAMachine


class TestTrialSignup(TrialOnAMachine):
	"""A signup for another product while a free trial is open adds that product's app to the open site."""

	def setUp(self):
		super().setUp()
		self.product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": "crm-" + frappe.generate_hash(length=6),
				"title": "CRM",
				"signup_app": "crm",
				"landing_route": "/crm",
			}
		).insert()
		self.enterContext(
			patch(
				"central.integrations.pilot._expected_gateway_url", return_value="https://pilot.example.test"
			)
		)
		self.pilot = self.enterContext(patch("central.integrations.pilot._request_pilot"))

	def test_the_signup_page_reads_the_open_trial(self):
		summary = get_open_trial(self.team.name)

		self.assertEqual(summary["site"], self.site().name)
		self.assertEqual(summary["state"], "Active")
		self.assertEqual(summary["product_title"], "Frappe Cloud")

	def test_a_member_of_another_team_of_the_owner_does_not_see_the_trial_site(self):
		member = create_user(f"member-{frappe.generate_hash(length=8)}@example.test")
		other = frappe.get_doc({"doctype": "Team", "team_name": "Other", "owner_user": "Administrator"})
		other.append("members", {"user": member, "role": "Admin", "resource_type": "*", "status": "Active"})
		other.insert()

		with self.set_user(member):
			summary = get_open_trial(other.name)

		self.assertEqual(summary["state"], "Active")
		self.assertNotIn("site", summary)
		self.assertNotIn("address", summary)

	def test_a_trial_still_being_set_up_is_named_too(self):
		frappe.db.delete("Site", {"server": self.server.name})
		frappe.db.set_value("Resource Action", {"server": self.server.name}, "status", "Dispatching")

		self.assertEqual(get_open_trial(self.team.name)["state"], "Setting up")

	def test_another_product_installs_on_the_open_trial_site(self):
		self.pilot.side_effect = [{"apps": [{"name": "frappe"}]}, {"task_id": "task-1", "status": "queued"}]

		result = install_trial_app(self.product.name, self.team.name)

		self.assertEqual(result, {"site": "site.local", "task_id": "task-1", "status": "queued"})
		self.pilot.assert_called_with(
			"POST",
			self.server.name,
			"https://pilot.example.test",
			"/api/v1/sites/site.local/apps",
			{"app": "crm"},
		)

	def test_an_app_the_site_has_already_is_not_installed_again(self):
		self.pilot.return_value = {"apps": [{"name": "frappe"}, {"name": "crm"}]}

		result = install_trial_app(self.product.name, self.team.name)

		self.assertEqual(result, {"site": "site.local", "task_id": None, "status": "success"})
		self.assertEqual(self.pilot.call_count, 1)

	def test_a_renamed_site_installs_under_the_name_its_bench_knows(self):
		self.site().db_set({"subdomain": "acme", "rename_task": "task-rename"})
		missing = requests.HTTPError(response=Mock(status_code=404))
		self.pilot.side_effect = [missing, {"apps": []}, {"task_id": "task-1", "status": "queued"}]

		result = install_trial_app(self.product.name, self.team.name)

		self.assertEqual(result["site"], "site.local")
		self.assertIn(f"/sites/{self.site().rename_target}/apps", self.pilot.call_args_list[0].args[3])

	def test_an_ended_trial_gets_no_new_app(self):
		self.site().db_set("trial_state", "Ended")

		with self.assertRaisesRegex(frappe.ValidationError, "running free trial"):
			install_trial_app(self.product.name, self.team.name)

	def test_a_site_that_does_not_answer_asks_the_customer_to_try_again(self):
		self.pilot.side_effect = requests.ConnectionError()

		with self.assertRaisesRegex(frappe.ValidationError, "did not answer"):
			install_trial_app(self.product.name, self.team.name)

	def test_the_install_progress_shows_the_queue(self):
		self.pilot.return_value = {"status": "queued", "queue_position": 2, "started_at": None}

		progress = get_trial_app_install("site.local", "task-1", self.product.name, self.team.name)

		self.assertEqual(progress["status"], "queued")
		self.assertEqual(progress["queue_position"], 2)

	def test_a_site_that_misses_a_poll_reads_as_unreachable(self):
		self.pilot.side_effect = requests.ConnectionError()

		progress = get_trial_app_install("site.local", "task-1", self.product.name, self.team.name)

		self.assertEqual(progress["status"], "unreachable")

	def test_a_failed_install_tells_the_customer_and_leaves_the_reason_on_the_site(self):
		self.pilot.return_value = {"status": "failed", "failure": {"code": "x", "message": "No room left"}}

		progress = get_trial_app_install("site.local", "task-1", self.product.name, self.team.name)

		self.assertEqual(progress["status"], "failed")
		self.assertEqual(
			progress["error"], "CRM could not be installed on your site. Try again in a few minutes."
		)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Site", "reference_name": self.site().name},
			pluck="content",
		)
		self.assertTrue(any("No room left" in comment for comment in comments))

	def test_the_install_progress_of_another_site_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			get_trial_app_install("other.example.test", "task-1", self.product.name, self.team.name)

	def test_the_new_app_opens_on_its_own_page(self):
		self.assertEqual(self.site().get_landing_route(self.product.name), "/crm")
		self.assertIsNone(self.site().get_landing_route())
