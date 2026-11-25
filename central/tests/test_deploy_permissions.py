from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy import api
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.infrastructure.doctype.github_installation.test_github_installation import (
	make_installation,
)
from central.tests.test_iam import ensure_user


class TestDeployPermissions(IntegrationTestCase):
	"""A team member reads the team's deploys with app:view, and changes nothing directly."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("deploy.scope.owner@example.test")
		self.viewer = ensure_user("deploy.scope.viewer@example.test")
		self.billing = ensure_user("deploy.scope.billing@example.test")
		self.suffix = frappe.generate_hash(length=8)
		patch.object(DeployRequest, "after_insert").start()
		self.addCleanup(patch.stopall)
		self.addCleanup(frappe.set_user, "Administrator")

		self.my_team = self.make_team("Deploy Mine", {self.viewer: "Viewer", self.billing: "Billing"})
		self.their_team = self.make_team("Deploy Theirs", {})
		self.my_app, self.my_request = self.make_deploy(self.my_team, "21")
		self.their_app, self.their_request = self.make_deploy(self.their_team, "22")

	def make_team(self, label: str, members: dict[str, str]) -> str:
		rows = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in members.items()]
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"{label} {self.suffix}",
				"owner_user": self.owner,
				"members": rows,
			}
		)
		return team.insert().name

	def make_deploy(self, team: str, repository_id: str) -> tuple[str, str]:
		app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team).name,
				"repository": f"octo/app-{repository_id}",
				"repository_id": repository_id,
				"branch": "main",
			}
		).insert()
		return app.name, DeployRequest.queue(app.name, "a" * 40).name

	def list_deploys(self, deploy_app: str) -> list[str]:
		"""What the console's list view reads through frappe.client.get_list."""
		return frappe.get_list("Deploy Request", filters={"deploy_app": deploy_app}, pluck="name")

	def test_a_viewer_reads_the_teams_deploys(self):
		frappe.set_user(self.viewer)
		self.assertEqual(self.list_deploys(self.my_app), [self.my_request])
		self.assertEqual(api.get_deploy_request(self.my_request)["status"], "Queued")
		self.assertIn(self.my_app, frappe.get_list("Deploy App", pluck="name"))

	def test_another_teams_deploys_are_hidden(self):
		frappe.set_user(self.viewer)
		self.assertEqual(self.list_deploys(self.their_app), [])
		with self.assertRaises(frappe.PermissionError):
			api.get_deploy_request(self.their_request)
		self.assertNotIn(self.their_app, frappe.get_list("Deploy App", pluck="name"))

	def test_a_viewer_lists_the_teams_apps_but_cannot_disable_them(self):
		frappe.set_user(self.viewer)
		self.assertEqual([app["name"] for app in api.get_apps(self.my_team)], [self.my_app])
		self.assertEqual(api.get_apps(self.their_team), [])
		with self.assertRaises(frappe.PermissionError):
			api.disable_app(self.my_app)

	def test_a_member_with_app_deploy_disables_only_the_teams_apps(self):
		frappe.set_user(self.owner)
		api.disable_app(self.my_app)
		self.assertEqual(frappe.db.get_value("Deploy App", self.my_app, "status"), "Disabled")

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			api.disable_app(self.their_app)
		self.assertEqual(frappe.db.get_value("Deploy App", self.their_app, "status"), "Active")

	def test_a_member_with_app_deploy_sets_and_removes_the_teams_secrets(self):
		frappe.set_user(self.owner)
		names = api.update_app_secrets(self.my_app, {"DATABASE_URL": "postgres://db", "TOKEN": "a"})
		self.assertEqual(names, ["DATABASE_URL", "TOKEN"])
		self.assertEqual(api.update_app_secrets(self.my_app, {"TOKEN": "b"}, ["DATABASE_URL"]), ["TOKEN"])

		frappe.set_user("Administrator")
		secrets = frappe.get_doc("Deploy App", self.my_app).secrets
		self.assertEqual([(row.key, row.get_password("value")) for row in secrets], [("TOKEN", "b")])

	def test_a_viewer_reads_secret_names_but_cannot_change_them(self):
		frappe.set_user(self.owner)
		api.update_app_secrets(self.my_app, {"TOKEN": "a"})

		frappe.set_user(self.viewer)
		self.assertEqual(api.get_app_secrets(self.my_app), ["TOKEN"])
		with self.assertRaises(frappe.PermissionError):
			api.update_app_secrets(self.my_app, {"TOKEN": "b"})
		with self.assertRaises(frappe.PermissionError):
			api.get_app_secrets(self.their_app)

	def test_another_teams_secrets_cannot_be_changed(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			api.update_app_secrets(self.their_app, {"TOKEN": "a"})

	def test_removing_a_secret_the_app_does_not_have_is_refused(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			api.update_app_secrets(self.my_app, unset=["MISSING"])

	def test_a_running_deploy_is_left_to_finish_when_its_app_is_disabled(self):
		frappe.set_user(self.owner)
		api.disable_app(self.my_app)
		self.assertEqual(frappe.db.get_value("Deploy Request", self.my_request, "status"), "Queued")

	def test_a_member_without_app_view_sees_no_deploy(self):
		frappe.set_user(self.billing)
		self.assertEqual(self.list_deploys(self.my_app), [])
		with self.assertRaises(frappe.PermissionError):
			api.get_deploy_request(self.my_request)

	def test_no_member_changes_a_deploy_directly(self):
		frappe.set_user(self.owner)
		request = frappe.get_doc("Deploy Request", self.my_request)
		self.assertTrue(frappe.has_permission("Deploy Request", "read", request))
		self.assertFalse(frappe.has_permission("Deploy Request", "write", request))
		self.assertFalse(
			frappe.has_permission("Deploy App", "delete", frappe.get_doc("Deploy App", self.my_app))
		)
