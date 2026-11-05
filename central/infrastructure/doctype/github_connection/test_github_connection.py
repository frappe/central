# Copyright (c) 2026, frappe and Contributors
# See license.txt

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.integrations.github import get_connection_attempt, oauth_callback, repository_token
from central.infrastructure.doctype.github_connection.github_connection import (
	GitHubConnection,
	GitHubConnectionAttempt,
	GitHubRepositoryNotGranted,
)
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.github import GitHubApp
from central.tests.test_iam import ensure_user

INSTALLATION = {"installation_id": "101", "account": "octo", "account_type": "User"}
PRIVATE = {"repository_id": "11", "full_name": "octo/private-app"}
OTHER = {"repository_id": "12", "full_name": "octo/other-app"}


def make_team(name: str, owner: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": name,
				"owner_user": owner,
				"members": [{"user": owner, "role": "Owner", "status": "Active"}],
			}
		)
		.insert()
		.name
	)


class IntegrationTestGitHubConnection(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("github.owner@example.test")
		self.team = make_team("GitHub Team", self.owner)
		PilotCredential.mint(team=self.team, pilot_credential_id="pilot-github")
		self.credential = frappe.get_doc("Pilot Credential", "pilot-github")
		frappe.db.delete("GitHub Connection")

	def test_a_new_grant_replaces_the_old_one_and_bumps_the_version(self):
		first = GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])
		second = GitHubConnection.grant(self.credential, INSTALLATION, [OTHER])

		self.assertEqual(first.name, second.name)
		self.assertEqual(second.version, 2)
		self.assertFalse(first.is_current(1))
		with self.assertRaises(GitHubRepositoryNotGranted):
			GitHubConnection.find_repository(self.credential, PRIVATE["full_name"])

	def test_a_new_github_app_disables_the_old_grants(self):
		connection = GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])
		settings = frappe.get_doc("Central Settings")
		self.addCleanup(
			frappe.db.set_single_value, "Central Settings", "github_app_id", settings.github_app_id
		)
		settings.github_app_id = f"{settings.github_app_id or ''}-replaced"
		settings.save()

		connection.reload()
		self.assertEqual(connection.status, "Disabled")

	def test_a_repository_removed_on_github_is_no_longer_granted(self):
		GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE, OTHER])

		GitHubConnection.remove_repositories(INSTALLATION["installation_id"], {PRIVATE["repository_id"]})

		with self.assertRaises(GitHubRepositoryNotGranted):
			GitHubConnection.find_repository(self.credential, PRIVATE["full_name"])
		_, repository_id = GitHubConnection.find_repository(self.credential, "OCTO/other-app")
		self.assertEqual(repository_id, OTHER["repository_id"])

	def test_a_repository_renamed_on_github_keeps_its_grant(self):
		GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])

		GitHubConnection.rename_repository(
			INSTALLATION["installation_id"], PRIVATE["repository_id"], "octo/renamed-app"
		)

		_, repository_id = GitHubConnection.find_repository(self.credential, "octo/renamed-app")
		self.assertEqual(repository_id, PRIVATE["repository_id"])

	def test_revoking_one_account_keeps_the_other_accounts(self):
		organization = {"installation_id": "202", "account": "octo-org", "account_type": "Organization"}
		GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])
		GitHubConnection.grant(
			self.credential, organization, [{"repository_id": "21", "full_name": "octo-org/app"}]
		)

		GitHubConnection.revoke(self.credential, INSTALLATION["installation_id"])

		with self.assertRaises(GitHubRepositoryNotGranted):
			GitHubConnection.find_repository(self.credential, PRIVATE["full_name"])
		self.assertEqual(GitHubConnection.find_repository(self.credential, "octo-org/app")[1], "21")

	def test_only_a_console_user_of_the_team_can_open_the_attempt(self):
		outsider = ensure_user("github.outsider@example.test")
		make_team("Outsider Team", outsider)
		attempt = GitHubConnectionAttempt.start(self.credential, "https://bench.example.test/settings")

		with self.assertRaises(frappe.PermissionError):
			GitHubConnectionAttempt.load(attempt.attempt_id).bind(outsider)

		GitHubConnectionAttempt.load(attempt.attempt_id).bind(self.owner)
		with self.assertRaises(frappe.PermissionError):
			GitHubConnectionAttempt.load(attempt.attempt_id).bind(ensure_user("github.second@example.test"))
		attempt.finish()

	def test_an_expired_link_still_leads_back_to_the_server(self):
		attempt = GitHubConnectionAttempt.start(self.credential, "https://bench.example.test/settings")
		attempt.bind(self.owner)
		attempt.finish()

		oauth_callback(state=attempt.state, code="code")
		self.assertEqual(frappe.local.response["location"], f"/dashboard/github/connect/{attempt.attempt_id}")

		frappe.set_user(self.owner)
		self.assertEqual(
			get_connection_attempt(attempt.attempt_id),
			{"is_expired": True, "return_url": "https://bench.example.test/settings"},
		)

	def test_a_pilot_gets_a_token_only_for_a_granted_and_unchanged_repository(self):
		GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])
		minted = {"token": "ghs_repository", "expires_at": "2099-01-01T00:00:00Z"}

		with (
			patch("frappe.get_request_header", return_value="pilot-token"),
			patch("central.api.pilot.PilotCredential.verify", return_value=self.credential),
			patch("central.api.integrations.github.GitHubApp") as app,
		):
			app.return_value.create_installation_token.return_value = minted
			self.assertEqual(repository_token(PRIVATE["full_name"]), minted)
			app.return_value.create_installation_token.assert_called_once_with(
				"101", PRIVATE["repository_id"]
			)

			with self.assertRaises(GitHubRepositoryNotGranted):
				repository_token(OTHER["full_name"])

			def regrant_while_minting(*args):
				GitHubConnection.grant(self.credential, INSTALLATION, [PRIVATE])
				return minted

			app.return_value.create_installation_token.side_effect = regrant_while_minting
			with self.assertRaises(frappe.PermissionError):
				repository_token(PRIVATE["full_name"])

	def test_only_the_attempt_user_gets_the_github_user_token(self):
		attempt = GitHubConnectionAttempt.start(self.credential, "https://bench.example.test/settings")
		attempt.bind(self.owner)

		with patch("central.api.integrations.github.GitHubApp") as app:
			app.return_value.exchange_code.return_value = "ghu_user"
			frappe.set_user(ensure_user("github.second@example.test"))
			oauth_callback(state=attempt.state, code="code")
			self.assertIsNone(GitHubConnectionAttempt.load(attempt.attempt_id).user_token)

			frappe.set_user(self.owner)
			oauth_callback(state=attempt.state, code="code")

		self.assertEqual(GitHubConnectionAttempt.load(attempt.attempt_id).user_token, "ghu_user")
		app.return_value.exchange_code.assert_called_once_with("code", attempt.code_verifier)
		attempt.finish()

	def test_a_cancelled_authorization_does_not_send_the_user_back_to_github(self):
		attempt = GitHubConnectionAttempt.start(self.credential, "https://bench.example.test/settings")
		attempt.bind(self.owner)
		frappe.set_user(self.owner)

		oauth_callback(state=attempt.state, error="access_denied")
		self.assertEqual(
			frappe.local.response["location"], f"/dashboard/github/connect/{attempt.attempt_id}?cancelled=1"
		)
		attempt.finish()

	def test_a_webhook_needs_the_signature_of_the_webhook_secret(self):
		settings = MagicMock(github_app_id="1", github_client_id="client", github_app_slug="app")
		settings.get_password.return_value = "secret"
		with patch("central.integrations.github.frappe.get_cached_doc", return_value=settings):
			app = GitHubApp()

		body = b'{"action": "deleted"}'
		signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
		self.assertTrue(app.is_valid_webhook_signature(body, signature))
		self.assertFalse(app.is_valid_webhook_signature(body + b" ", signature))
		self.assertFalse(app.is_valid_webhook_signature(body, None))
