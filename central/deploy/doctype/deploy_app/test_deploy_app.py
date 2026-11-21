# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user

REPOSITORY = {"repository_id": "11", "full_name": "octo/app", "default_branch": "main"}


class IntegrationTestDeployApp(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		owner = ensure_user("deploy.app.owner@example.test")
		self.team = make_team("Deploy App Team", owner)
		self.installation = make_installation(self.team)

		app = patch("central.deploy.doctype.deploy_app.deploy_app.GitHubDeployApp").start()
		self.addCleanup(patch.stopall)
		app.return_value.has_branch.side_effect = lambda *args: args[-1] in ("main", "staging")

	def test_a_repository_deploys_from_its_default_branch(self):
		app = DeployApp.add(self.installation, REPOSITORY)
		self.assertEqual(
			(app.repository, app.repository_id, app.branch, app.installation),
			("octo/app", "11", "main", self.installation.name),
		)

	def test_one_repository_can_deploy_from_two_branches(self):
		DeployApp.add(self.installation, REPOSITORY)
		DeployApp.add(self.installation, REPOSITORY, "staging")
		self.assertEqual(frappe.db.count("Deploy App", {"team": self.team, "repository_id": "11"}), 2)

	def test_adding_the_same_branch_again_keeps_one_app(self):
		first = DeployApp.add(self.installation, REPOSITORY)
		self.assertEqual(DeployApp.add(self.installation, REPOSITORY).name, first.name)

	def test_a_branch_missing_on_github_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			DeployApp.add(self.installation, REPOSITORY, "typo")

	def test_a_push_finds_the_apps_of_its_branch(self):
		main = DeployApp.add(self.installation, REPOSITORY)
		DeployApp.add(self.installation, REPOSITORY, "staging")
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [main.name])
		self.assertEqual(DeployApp.get_for_push("101", "11", "feature"), [])
		self.assertEqual(DeployApp.get_for_push("202", "11", "main"), [])

		self.installation.status = "Disabled"
		self.installation.save()
		self.assertEqual(DeployApp.get_for_push("101", "11", "main"), [])
