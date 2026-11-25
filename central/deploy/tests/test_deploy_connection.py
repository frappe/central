# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.integrations.github import oauth_callback
from central.deploy import api
from central.deploy.connection import (
	DeployConnectionAttempt,
	state_key,
	to_owner_and_name,
)
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

INSTALLATION = {
	"installation_id": "101",
	"account": "octo",
	"account_type": "Organization",
	"permissions": {"contents": "read", "metadata": "read", "statuses": "write"},
	"events": ["push", "repository"],
}
# An installation made before the App asked for commit statuses and pushes.
PILOT_ONLY_INSTALLATION = {**INSTALLATION, "permissions": {"contents": "read"}, "events": ["repository"]}
REPOSITORY = {"repository_id": "11", "full_name": "octo/app", "default_branch": "main", "is_admin": True}


class IntegrationTestDeployConnection(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Central Settings", "wildcard_domain", "example.test")
		self.owner = ensure_user("github.deploy.owner@example.test")
		self.outsider = ensure_user("github.deploy.outsider@example.test")
		self.team = make_team("GitHub Deploy Team", self.owner)
		self.other_team = make_team("GitHub Deploy Other Team", self.owner)
		self.region = ensure_region("github-deploy-test")

		app = patch("central.deploy.connection.GitHubApp").start()
		self.addCleanup(patch.stopall)
		self.github = app.return_value
		self.github.exchange_code.return_value = "user-token"
		self.github.get_authorize_url.return_value = "sign-in-url"
		self.github.get_user_installations.return_value = [INSTALLATION]
		self.github.get_install_url.return_value = "install-url"
		self.github.get_installation_settings_url.return_value = "installation-settings-url"
		self.repositories = app.return_value.get_user_repositories
		self.repositories.return_value = [REPOSITORY]
		branches = patch("central.deploy.doctype.deploy_app.deploy_app.GitHubApp").start()
		branches.return_value.has_branch.return_value = True

	def start(self) -> str:
		return DeployConnectionAttempt.start(self.team, self.owner, "Octo/App", self.region)

	def test_the_signed_in_user_connects_a_repository_through_the_api(self):
		frappe.set_user(self.owner)
		started = api.connect_repository(self.team, "octo/app", self.region)
		self.assertEqual(started["sign_in_url"], "sign-in-url")

		DeployConnectionAttempt.verify(started["state"], "code", "101", self.owner)
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			api.complete_repository_connection(started["state"])

		frappe.set_user(self.owner)
		app = api.complete_repository_connection(started["state"])
		self.assertEqual((app["repository"], app["branch"]), ("octo/app", "main"))

	def test_a_github_url_or_remote_is_read_as_owner_and_name(self):
		for repository in (
			"octo/app",
			"https://github.com/octo/app",
			"https://www.github.com/octo/app/",
			"https://github.com/octo/app.git",
			"git@github.com:octo/app.git",
		):
			with self.subTest(repository):
				self.assertEqual(to_owner_and_name(repository), "octo/app")
		self.assertEqual(to_owner_and_name("octo/app.js"), "octo/app.js")

	def test_a_repository_that_is_not_on_github_or_not_owner_and_name_is_refused(self):
		for repository in ("octo", "octo/app/tree/main", "https://gitlab.com/octo/app"):
			with self.subTest(repository), self.assertRaises(frappe.ValidationError):
				DeployConnectionAttempt.start(self.team, self.owner, repository, self.region)

	def test_the_attempt_keeps_owner_and_name_from_a_url(self):
		state = DeployConnectionAttempt.start(
			self.team, self.owner, "https://github.com/Octo/App", self.region
		)
		DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		self.assertEqual(DeployConnectionAttempt.complete(state, self.owner).repository, "octo/app")

	def test_a_sign_in_finds_the_repository_in_an_installation_already_on_the_account(self):
		state = self.start()
		self.assertIsNone(DeployConnectionAttempt.verify(state, "code", None, self.owner))
		# Only the sign-in sent a PKCE challenge.
		self.assertIsNotNone(self.github.exchange_code.call_args.args[1])
		self.assertEqual(DeployConnectionAttempt.complete(state, self.owner).repository, "octo/app")

	def test_a_code_from_an_install_is_traded_without_a_verifier(self):
		DeployConnectionAttempt.verify(self.start(), "code", "101", self.owner)
		self.assertIsNone(self.github.exchange_code.call_args.args[1])

	def test_a_repository_added_on_github_after_the_sign_in_is_found_on_the_next_poll(self):
		self.repositories.return_value = [{**REPOSITORY, "full_name": "octo/docs"}]
		state = self.start()
		self.assertEqual(DeployConnectionAttempt.verify(state, "code", None, self.owner), "install-url")
		with self.assertRaisesRegex(frappe.PermissionError, "Install the GitHub App first"):
			DeployConnectionAttempt.complete(state, self.owner)

		# GitHub sends no callback when a repository is added to an installation.
		self.repositories.return_value = [REPOSITORY]
		self.assertEqual(DeployConnectionAttempt.complete(state, self.owner).repository, "octo/app")

	def test_the_user_token_is_kept_encrypted_and_dropped_once_verified(self):
		self.repositories.return_value = []
		state = self.start()
		DeployConnectionAttempt.verify(state, "code", None, self.owner)
		stored = frappe.cache.get_value(state_key(state))
		self.assertNotIn("user-token", stored)

		self.repositories.return_value = [REPOSITORY]
		DeployConnectionAttempt.verify(state, "code", None, self.owner)
		self.assertNotIn("user_token", frappe.cache.get_value(state_key(state)))

	def test_the_callback_sends_the_user_to_install_the_app_when_no_installation_has_the_repository(self):
		self.repositories.return_value = []
		state = self.start()
		frappe.set_user(self.owner)
		oauth_callback(state=state, code="code")
		self.assertEqual(
			(frappe.local.response.get("type"), frappe.local.response.get("location")),
			("redirect", "install-url"),
		)

	def test_the_callback_sends_the_user_to_accept_the_deploy_permissions_on_an_older_installation(self):
		self.github.get_user_installations.return_value = [PILOT_ONLY_INSTALLATION]
		state = self.start()
		frappe.set_user(self.owner)
		oauth_callback(state=state, code="code")
		self.assertEqual(
			(frappe.local.response.get("type"), frappe.local.response.get("location")),
			("redirect", "installation-settings-url"),
		)
		self.github.get_installation_settings_url.assert_called_with(PILOT_ONLY_INSTALLATION)

	def test_a_deploy_waits_for_the_permissions_and_connects_on_the_next_poll_once_accepted(self):
		self.github.get_user_installations.return_value = [PILOT_ONLY_INSTALLATION]
		state = self.start()
		DeployConnectionAttempt.verify(state, "code", None, self.owner)
		with self.assertRaisesRegex(
			frappe.PermissionError, "Accept the GitHub App's new permissions on octo"
		):
			DeployConnectionAttempt.complete(state, self.owner)

		# GitHub sends no callback when an owner accepts new permissions.
		self.github.get_user_installations.return_value = [INSTALLATION]
		self.assertEqual(DeployConnectionAttempt.complete(state, self.owner).repository, "octo/app")

	def test_the_one_callback_sends_a_deploy_attempt_to_the_deploy_flow(self):
		state = self.start()
		frappe.set_user(self.owner)
		with patch("frappe.respond_as_web_page") as page:
			oauth_callback(state=state, code="code")
		self.assertEqual(page.call_args.args[0], "GitHub connected")
		self.assertTrue(DeployConnectionAttempt.is_verified(state, self.owner))

	def test_a_verified_installation_is_linked_once(self):
		state = self.start()
		self.assertFalse(DeployConnectionAttempt.is_verified(state, self.owner))
		DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		self.assertTrue(DeployConnectionAttempt.is_verified(state, self.owner))
		self.assertFalse(frappe.db.exists("GitHub Installation", {"team": self.team}))

		app = DeployConnectionAttempt.complete(state, self.owner)
		installation = frappe.get_doc("GitHub Installation", app.installation)
		self.assertEqual((installation.team, installation.account), (self.team, "octo"))
		self.assertEqual(
			(app.team, app.repository, app.branch, app.region), (self.team, "octo/app", "main", self.region)
		)
		with self.assertRaises(frappe.DoesNotExistError):
			DeployConnectionAttempt.complete(state, self.owner)

	def test_an_attempt_verified_in_another_process_is_seen(self):
		state = self.start()
		key = frappe.cache.make_key(state_key(state))
		copy_from_start = frappe.local.cache[key]

		DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		frappe.local.cache[key] = copy_from_start
		self.assertTrue(DeployConnectionAttempt.is_verified(state, self.owner))

	def test_an_installation_the_user_cannot_access_is_refused(self):
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.verify(state, "code", "999", self.owner)
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.complete(state, self.owner)

	def test_another_user_cannot_finish_the_link(self):
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.verify(state, "code", "101", self.outsider)

		DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.complete(state, self.outsider)

	def test_a_user_without_deploy_access_cannot_start(self):
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.start(self.team, self.outsider, "octo/app", self.region)

	def test_a_repository_the_user_cannot_access_is_refused(self):
		# The installation covers the repository, but this user's own list doesn't.
		self.repositories.return_value = [{**REPOSITORY, "full_name": "octo/docs"}]
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		self.assertFalse(DeployConnectionAttempt.is_verified(state, self.owner))

	def test_a_user_who_is_not_admin_on_the_repository_is_refused(self):
		self.repositories.return_value = [{**REPOSITORY, "is_admin": False}]
		state = self.start()
		with self.assertRaises(frappe.PermissionError):
			DeployConnectionAttempt.verify(state, "code", "101", self.owner)
		self.assertFalse(frappe.db.exists("Deploy App", {"team": self.team}))

	def test_an_unknown_region_is_refused_before_github(self):
		with self.assertRaises(frappe.DoesNotExistError):
			DeployConnectionAttempt.start(self.team, self.owner, "octo/app", "no-such-region")
