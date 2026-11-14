# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.deploy_app.deploy_app import DeployApp
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.tests.test_iam import ensure_user

REPOSITORY = {"repository_id": "11", "full_name": "octo/app", "default_branch": "main"}


class IntegrationTestDeployApp(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		owner = ensure_user("deploy.app.owner@example.test")
		self.team = make_team("Deploy App Team", owner)
		self.installation = make_installation(self.team)

		app = patch("central.infrastructure.doctype.deploy_app.deploy_app.GitHubDeployApp").start()
		self.addCleanup(patch.stopall)
		app.return_value.get_installation_repositories.return_value = [REPOSITORY]
		app.return_value.has_branch.side_effect = lambda *args: args[-1] in ("main", "staging")

	def test_a_repository_deploys_from_its_default_branch(self):
		app = DeployApp.add(self.team, "Octo/App")
		self.assertEqual(
			(app.repository, app.repository_id, app.branch, app.installation),
			("octo/app", "11", "main", self.installation.name),
		)

	def test_one_repository_can_deploy_from_two_branches(self):
		DeployApp.add(self.team, "octo/app")
		DeployApp.add(self.team, "octo/app", "staging")
		self.assertEqual(frappe.db.count("Deploy App", {"team": self.team, "repository_id": "11"}), 2)

	def test_adding_the_same_branch_again_keeps_one_app(self):
		first = DeployApp.add(self.team, "octo/app")
		self.assertEqual(DeployApp.add(self.team, "octo/app").name, first.name)

	def test_a_branch_missing_on_github_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			DeployApp.add(self.team, "octo/app", "typo")

	def test_a_repository_outside_the_teams_installations_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			DeployApp.add(self.team, "octo/other")

		self.installation.db_set("status", "Disabled")
		with self.assertRaises(frappe.DoesNotExistError):
			DeployApp.add(self.team, "octo/app")

	def test_a_push_finds_the_apps_of_its_branch(self):
		main = DeployApp.add(self.team, "octo/app")
		DeployApp.add(self.team, "octo/app", "staging")
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [main.name])
		self.assertEqual(DeployApp.get_for_push("101", "11", "feature"), [])
		self.assertEqual(DeployApp.get_for_push("202", "11", "main"), [])

		self.installation.db_set("status", "Disabled")
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [])
