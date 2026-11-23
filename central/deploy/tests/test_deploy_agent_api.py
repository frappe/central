from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy import api
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user


class IntegrationTestDeployAgentAPI(IntegrationTestCase):
	"""The deploy agent gets its app's build and reports on it with the app's token."""

	def setUp(self):
		frappe.set_user("Administrator")
		team = make_team("Deploy Agent Team", ensure_user("deploy.agent.owner@example.test"))
		installation = make_installation(team).name
		self.app = self.make_app(team, installation, "11")
		self.other_app = self.make_app(team, installation, "12")
		with patch.object(DeployRequest, "after_insert"):
			self.request = DeployRequest.queue(self.app.name, "a" * 40)
		self.request.set_status("Building")
		patch.object(DeployRequest, "get_build_payload", return_value={"commit": "a" * 40}).start()
		self.addCleanup(patch.stopall)

	def make_app(self, team: str, installation: str, repository_id: str):
		return frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": installation,
				"repository": f"octo/app-{repository_id}",
				"repository_id": repository_id,
				"branch": "main",
			}
		).insert()

	def call_as(self, app, method, **kwargs):
		credential = f"{app.name}:{app.get_password('agent_token')}"
		with patch.object(api.frappe, "get_request_header", return_value=credential):
			return method(**kwargs)

	def test_the_agent_gets_a_build_until_it_reports_on_it(self):
		self.assertEqual(self.call_as(self.app, api.get_build), {"commit": "a" * 40})
		self.assertFalse(frappe.db.get_value("Deploy Request", self.request.name, "build_status"))
		self.assertEqual(self.call_as(self.app, api.get_build), {"commit": "a" * 40})
		self.call_as(self.app, api.report_build, deploy_request=self.request.name, status="Running")
		self.assertIsNone(self.call_as(self.app, api.get_build))

	def test_another_apps_agent_gets_nothing_and_cannot_report(self):
		self.assertIsNone(self.call_as(self.other_app, api.get_build))
		with self.assertRaises(frappe.PermissionError):
			self.call_as(
				self.other_app, api.report_build, deploy_request=self.request.name, status="Succeeded"
			)

	def test_a_wrong_token_is_refused(self):
		with (
			patch.object(api.frappe, "get_request_header", return_value=f"{self.app.name}:wrong"),
			self.assertRaises(frappe.AuthenticationError),
		):
			api.get_build()

	def test_a_report_saves_the_status_and_the_end_of_the_log(self):
		reply = self.call_as(
			self.app, api.report_build, deploy_request=self.request.name, status="Failed", log="x" * 30_000
		)
		self.assertEqual(reply, {"cancel": False})
		status, log, reported_at = frappe.db.get_value(
			"Deploy Request", self.request.name, ["build_status", "build_log", "build_reported_at"]
		)
		self.assertEqual((status, len(log)), ("Failed", api.BUILD_LOG_CHARACTERS))
		self.assertIsNotNone(reported_at)

	def test_a_superseded_build_tells_the_agent_to_cancel(self):
		with patch.object(DeployRequest, "after_insert"):
			DeployRequest.queue(self.app.name, "b" * 40)
		reply = self.call_as(self.app, api.report_build, deploy_request=self.request.name, status="Running")
		self.assertEqual(reply, {"cancel": True})

	def test_a_late_report_on_a_failed_build_tells_the_agent_to_cancel(self):
		self.request.set_status("Failed")
		reply = self.call_as(self.app, api.report_build, deploy_request=self.request.name, status="Running")
		self.assertEqual(reply, {"cancel": True})

	def report_release(self, app, status: str, logs: str = ""):
		return self.call_as(
			app, api.report_deployment_status, deploy_request=self.request.name, status=status, logs=logs
		)

	def test_a_release_report_saves_the_status_and_the_end_of_the_log(self):
		self.report_release(self.app, "Releasing")
		self.report_release(self.app, "Failed", logs="x" * 30_000)
		status, log, reported_at = frappe.db.get_value(
			"Deploy Request", self.request.name, ["release_status", "release_log", "release_reported_at"]
		)
		self.assertEqual((status, len(log)), ("Failed", api.BUILD_LOG_CHARACTERS))
		self.assertIsNotNone(reported_at)

	def test_another_apps_agent_cannot_report_a_release(self):
		with self.assertRaises(frappe.PermissionError):
			self.report_release(self.other_app, "Live")

	def test_an_unknown_release_status_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.report_release(self.app, "Succeeded")
