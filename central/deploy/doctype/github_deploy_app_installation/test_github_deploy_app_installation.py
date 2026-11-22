# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
	GitHubDeployAppInstallation,
	state_key,
)
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

INSTALLATION = {"installation_id": "101", "account": "octo", "account_type": "Organization"}
REPOSITORY = {"repository_id": "11", "full_name": "octo/app", "default_branch": "main", "is_admin": True}


def make_installation(team: str, installation_id: str = "101") -> Document:
	return frappe.get_doc(
		{
			"doctype": "GitHub Deploy App Installation",
			"team": team,
			"installation_id": installation_id,
			"account": "octo",
			"account_type": "Organization",
		}
	).insert()


class IntegrationTestGitHubDeployAppInstallation(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("github.deploy.owner@example.test")
		self.outsider = ensure_user("github.deploy.outsider@example.test")
		self.team = make_team("GitHub Deploy Team", self.owner)
		self.other_team = make_team("GitHub Deploy Other Team", self.owner)
		self.region = ensure_region("github-deploy-test")

		app = patch(
			"central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation.GitHubDeployApp"
		).start()
		self.addCleanup(patch.stopall)
		app.return_value.get_user_installations.return_value = [INSTALLATION]
		self.repositories = app.return_value.get_user_repositories
		self.repositories.return_value = [REPOSITORY]
		branches = patch("central.deploy.doctype.deploy_app.deploy_app.GitHubDeployApp").start()
		branches.return_value.has_branch.return_value = True

	def start(self) -> str:
		return GitHubDeployAppInstallation.start(self.team, self.owner, "Octo/App", self.region)

	def test_a_team_links_an_installation_once(self):
		make_installation(self.team)
		with self.assertRaises(frappe.UniqueValidationError):
			make_installation(self.team)

	def test_two_teams_can_link_the_same_installation(self):
		make_installation(self.team)
		self.assertEqual(make_installation(self.other_team).status, "Active")

	def test_a_verified_installation_is_linked_once(self):
		state = self.start()
		self.assertFalse(GitHubDeployAppInstallation.is_verified(state, self.owner))
		GitHubDeployAppInstallation.verify(state, "code", "101", self.owner)
		self.assertTrue(GitHubDeployAppInstallation.is_verified(state, self.owner))
		self.assertFalse(frappe.db.exists("GitHub Deploy App Installation", {"team": self.team}))

		app = GitHubDeployAppInstallation.complete(state, self.owner)
		installation = frappe.get_doc("GitHub Deploy App Installation", app.installation)
		self.assertEqual((installation.team, installation.account), (self.team, "octo"))
		self.assertEqual(
			(app.team, app.repository, app.branch, app.region), (self.team, "octo/app", "main", self.region)
		)
		with self.assertRaises(frappe.DoesNotExistError):
			GitHubDeployAppInstallation.complete(state, self.owner)

	def test_an_attempt_verified_in_another_process_is_seen(self):
		state = self.start()
		key = frappe.cache.make_key(state_key(state))
		copy_from_start = frappe.local.cache[key]

		GitHubDeployAppInstallation.verify(state, "code", "101", self.owner)
		frappe.local.cache[key] = copy_from_start
		self.assertTrue(GitHubDeployAppInstallation.is_verified(state, self.owner))

	def test_an_installation_the_user_cannot_access_is_refused(self):
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.verify(state, "code", "999", self.owner)
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.complete(state, self.owner)

	def test_another_user_cannot_finish_the_link(self):
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.verify(state, "code", "101", self.outsider)

		GitHubDeployAppInstallation.verify(state, "code", "101", self.owner)
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.complete(state, self.outsider)

	def test_a_user_without_deploy_access_cannot_start(self):
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.start(self.team, self.outsider, "octo/app", self.region)

	def test_a_repository_the_user_cannot_access_is_refused(self):
		# The installation covers the repository, but this user's own list doesn't.
		self.repositories.return_value = [{**REPOSITORY, "full_name": "octo/docs"}]
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.verify(state, "code", "101", self.owner)
		self.assertFalse(GitHubDeployAppInstallation.is_verified(state, self.owner))

	def test_a_user_who_is_not_admin_on_the_repository_is_refused(self):
		self.repositories.return_value = [{**REPOSITORY, "is_admin": False}]
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			GitHubDeployAppInstallation.verify(state, "code", "101", self.owner)
		self.assertFalse(frappe.db.exists("Deploy App", {"team": self.team}))

	def test_an_unknown_region_is_refused_before_github(self):
		with self.assertRaises(frappe.DoesNotExistError):
			GitHubDeployAppInstallation.start(self.team, self.owner, "octo/app", "no-such-region")
