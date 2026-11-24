import hashlib
import hmac
import json
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy.api import webhook
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.deploy.github import GitHubDeployApp
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.integrations.github import GitHubApp
from central.tests.test_iam import ensure_user

PUSH = {
	"ref": "refs/heads/main",
	"after": "a" * 40,
	"installation": {"id": 101},
	"repository": {"id": 11, "full_name": "octo/app"},
}


def deploy_settings() -> MagicMock:
	settings = MagicMock(
		github_app_id=None,
		github_deploy_app_id="2",
		github_deploy_client_id="deploy-client",
		github_deploy_app_slug="deploy-app",
	)
	settings.get_password.side_effect = lambda field, raise_exception=True: {
		"github_deploy_webhook_secret": "deploy-secret"
	}.get(field)
	return settings


class IntegrationTestGitHubDeploy(IntegrationTestCase):
	def setUp(self):
		self.settings = patch(
			"central.integrations.github.frappe.get_cached_doc", return_value=deploy_settings()
		)
		self.settings.start()
		self.addCleanup(self.settings.stop)

	def deliver(self, delivery: str, secret: bytes = b"deploy-secret", payload: dict = PUSH) -> MagicMock:
		body = json.dumps(payload).encode()
		headers = {
			"X-Hub-Signature-256": "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest(),
			"X-GitHub-Delivery": delivery,
			"X-GitHub-Event": "push",
		}
		with (
			patch("frappe.request", MagicMock(get_data=MagicMock(return_value=body))),
			patch("frappe.get_request_header", side_effect=headers.get),
			patch("central.deploy.api.DeployRequest.queue") as queue,
		):
			webhook()
		return queue

	def test_the_deploy_app_reads_its_own_settings(self):
		app = GitHubDeployApp()
		self.assertEqual((app.app_id, app.client_id, app.slug), ("2", "deploy-client", "deploy-app"))
		self.assertTrue(GitHubDeployApp.is_configured())
		self.assertFalse(GitHubApp.is_configured())
		self.assertTrue(
			GitHubDeployApp.callback_url().endswith("/api/method/central.deploy.api.oauth_callback")
		)

	def test_a_commit_status_is_posted_with_a_token_that_only_writes_statuses(self):
		app = GitHubDeployApp()
		with (
			patch.object(GitHubDeployApp, "_app_jwt", return_value="jwt"),
			patch.object(
				GitHubDeployApp, "_request", return_value={"token": "t", "expires_at": "x"}
			) as request,
		):
			app.set_commit_status("101", "11", "octo/app", "a" * 40, "failure", "x" * 200)
		token_call, status_call = request.call_args_list
		self.assertEqual(
			token_call.kwargs["json"], {"repository_ids": [11], "permissions": {"statuses": "write"}}
		)
		self.assertTrue(status_call.args[1].endswith("/repos/octo/app/statuses/" + "a" * 40))
		self.assertEqual(
			status_call.kwargs["json"],
			{"state": "failure", "description": "x" * 140, "context": "Deploy", "target_url": None},
		)

	def test_a_delivery_is_handled_once(self):
		self.make_app()
		delivery = frappe.generate_hash()
		self.deliver(delivery).assert_called()
		self.deliver(delivery).assert_not_called()

	def test_a_push_signed_with_another_secret_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.deliver(frappe.generate_hash(), secret=b"pilot-secret")

	def make_app(self) -> str:
		team = make_team("GitHub Deploy Push Team", ensure_user("github.deploy.push@example.test"))
		return (
			frappe.get_doc(
				{
					"doctype": "Deploy App",
					"team": team,
					"installation": make_installation(team).name,
					"repository": "octo/app",
					"repository_id": "11",
					"branch": "main",
				}
			)
			.insert()
			.name
		)

	def test_a_push_to_a_deployed_branch_queues_its_apps(self):
		app = self.make_app()
		delivery = frappe.generate_hash()
		# Rows from the class's other tests may match the same push too.
		self.assertIn(call(app, "a" * 40, delivery), self.deliver(delivery).call_args_list)

		self.deliver(frappe.generate_hash(), payload={**PUSH, "ref": "refs/tags/main"}).assert_not_called()
		self.deliver(frappe.generate_hash(), payload={**PUSH, "deleted": True}).assert_not_called()
