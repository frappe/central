import hashlib
import hmac
import json
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.integrations.github import create_app_manifest, webhook
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.test_github_installation import (
	make_installation,
)
from central.integrations.github import GitHubApp
from central.tests.test_iam import ensure_user

PUSH = {
	"ref": "refs/heads/main",
	"after": "a" * 40,
	"installation": {"id": 101},
	"repository": {"id": 11, "full_name": "octo/app"},
}


def app_settings() -> MagicMock:
	settings = MagicMock(github_app_id="2", github_client_id="client", github_app_slug="app")
	settings.get_password.side_effect = lambda field, raise_exception=True: {
		"github_webhook_secret": "app-secret"
	}.get(field)
	return settings


class IntegrationTestGitHubDeploy(IntegrationTestCase):
	def setUp(self):
		self.settings = patch(
			"central.integrations.github.frappe.get_cached_doc", return_value=app_settings()
		)
		self.settings.start()
		self.addCleanup(self.settings.stop)

	def deliver(self, delivery: str, secret: bytes = b"app-secret", payload: dict = PUSH) -> MagicMock:
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

	def test_deploys_and_servers_share_one_github_app_and_its_callback(self):
		app = GitHubApp()
		self.assertEqual((app.app_id, app.client_id, app.slug), ("2", "client", "app"))
		self.assertTrue(
			GitHubApp.callback_url().endswith("/api/method/central.api.integrations.github.oauth_callback")
		)

	def test_the_app_manifest_asks_for_what_deploys_need(self):
		frappe.set_user("Administrator")
		url = "https://central.example.test"
		with (
			patch("central.api.integrations.github.central_url", return_value=url),
			patch("central.integrations.github.central_url", return_value=url),
		):
			manifest = json.loads(create_app_manifest("Frappe Cloud")["manifest"])
		self.assertEqual(manifest["default_permissions"]["statuses"], "write")
		self.assertIn("push", manifest["default_events"])
		self.assertEqual(
			manifest["callback_urls"], [f"{url}/api/method/central.api.integrations.github.oauth_callback"]
		)

	def test_a_commit_status_is_posted_with_a_token_that_only_writes_statuses(self):
		app = GitHubApp()
		with (
			patch.object(GitHubApp, "_app_jwt", return_value="jwt"),
			patch.object(GitHubApp, "_request", return_value={"token": "t", "expires_at": "x"}) as request,
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
			self.deliver(frappe.generate_hash(), secret=b"other-secret")

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
