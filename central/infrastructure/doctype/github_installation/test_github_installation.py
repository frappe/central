# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.infrastructure.doctype.github_connection.github_connection import GitHubConnection
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.github_installation import GitHubInstallation
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.tests.test_iam import ensure_user

INSTALLATION = {"installation_id": "101", "account": "octo", "account_type": "Organization"}
REPOSITORY = {"repository_id": "11", "full_name": "octo/app"}


def make_installation(team: str, installation_id: str = "101") -> Document:
	return frappe.get_doc(
		{
			"doctype": "GitHub Installation",
			"team": team,
			"installation_id": installation_id,
			"account": "octo",
			"account_type": "Organization",
		}
	).insert()


class IntegrationTestGitHubInstallation(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("github.installation.owner@example.test")
		self.team = make_team("GitHub Installation Team", self.owner)
		self.other_team = make_team("GitHub Installation Other Team", self.owner)

	def test_a_team_links_an_installation_once(self):
		make_installation(self.team)
		with self.assertRaises(frappe.UniqueValidationError):
			make_installation(self.team)

	def test_two_teams_can_link_the_same_installation(self):
		make_installation(self.team)
		self.assertEqual(make_installation(self.other_team).status, "Active")

	def test_a_server_grant_and_a_deploy_app_share_the_team_installation(self):
		credential = self.make_credential()
		connection = GitHubConnection.grant(credential, INSTALLATION, [REPOSITORY])
		app = self.make_app(GitHubInstallation.link(self.team, INSTALLATION).name)

		self.assertEqual(connection.installation, app.installation)
		self.assertEqual((connection.get_installation_id(), app.get_installation_id()), ("101", "101"))
		self.assertEqual(connection.account, "octo")

	def test_an_installation_removed_on_github_stops_its_grants_and_deploys(self):
		credential = self.make_credential()
		connection = GitHubConnection.grant(credential, INSTALLATION, [REPOSITORY])
		app = self.make_app(connection.installation)

		GitHubInstallation.disable_installation("101")

		self.assertEqual(GitHubConnection.get_active(credential), [])
		self.assertFalse(connection.is_current(connection.version))
		self.assertEqual(frappe.db.get_value("Deploy App", app.name, "status"), "Disabled")

	def test_a_suspension_pauses_deploys_until_github_unsuspends_but_grants_must_connect_again(self):
		credential = self.make_credential()
		connection = GitHubConnection.grant(credential, INSTALLATION, [REPOSITORY])
		app = self.make_app(connection.installation)

		GitHubInstallation.suspend_installation("101")
		self.assertNotIn(app.name, DeployApp.get_for_push("101", "11", "main"))
		self.assertEqual(frappe.db.get_value("Deploy App", app.name, "status"), "Active")

		GitHubInstallation.unsuspend_installation("101")
		self.assertIn(app.name, DeployApp.get_for_push("101", "11", "main"))
		self.assertEqual(GitHubConnection.get_active(credential), [])

	def test_a_suspended_installation_cannot_be_linked(self):
		with self.assertRaisesRegex(frappe.PermissionError, "suspended on octo"):
			GitHubInstallation.link(self.team, {**INSTALLATION, "is_suspended": True})

	def test_reconnecting_one_server_after_a_suspension_does_not_restore_another_servers_grant(self):
		first = GitHubConnection.grant(self.make_credential(), INSTALLATION, [REPOSITORY])
		PilotCredential.mint(team=self.team, pilot_credential_id="pilot-github-installation-other")
		other_credential = frappe.get_doc("Pilot Credential", "pilot-github-installation-other")
		other = GitHubConnection.grant(other_credential, INSTALLATION, [REPOSITORY])

		GitHubInstallation.suspend_installation("101")
		GitHubConnection.grant(
			frappe.get_doc("Pilot Credential", first.pilot_credential), INSTALLATION, [REPOSITORY]
		)

		self.assertEqual(GitHubConnection.get_active(other_credential), [])
		self.assertFalse(other.is_current(other.version))

	def test_linking_again_makes_a_disabled_installation_active(self):
		installation = make_installation(self.team)
		GitHubInstallation.disable_installation("101")

		self.assertEqual(GitHubInstallation.link(self.team, INSTALLATION).name, installation.name)
		self.assertTrue(GitHubInstallation.is_active(installation.name))

	def make_credential(self) -> PilotCredential:
		PilotCredential.mint(team=self.team, pilot_credential_id="pilot-github-installation")
		return frappe.get_doc("Pilot Credential", "pilot-github-installation")

	def make_app(self, installation: str) -> Document:
		return frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": self.team,
				"installation": installation,
				"repository": REPOSITORY["full_name"],
				"repository_id": REPOSITORY["repository_id"],
				"branch": "main",
			}
		).insert()
