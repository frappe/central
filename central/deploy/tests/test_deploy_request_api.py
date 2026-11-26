from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.deploy import api
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.test_github_installation import (
	make_installation,
)
from central.tests.test_iam import ensure_user


def at(minute: int) -> datetime:
	return datetime(2026, 11, 24, 12, minute)


class IntegrationTestDeployRequestAPI(IntegrationTestCase):
	"""What the console reads about an app's deploys."""

	def setUp(self):
		frappe.set_user("Administrator")
		patch.object(DeployRequest, "after_insert").start()
		self.addCleanup(patch.stopall)
		team = make_team("Deploy Request API Team", ensure_user("deploy.request.api@example.test"))
		app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team).name,
				"repository": "octo/app",
				"repository_id": "11",
				"branch": "main",
			}
		).insert()
		self.request = DeployRequest.queue(app.name, "a" * 40)

	def test_a_deploy_shows_its_pipeline_tasks_its_output_and_its_error(self):
		self.request.db_set(
			{"status": "Failed", "error": "DeployBuildError: The build failed.", "build_log": "npm ERR\n"}
		)
		tasks = [frappe._dict(method_title="Wait For Build", status="Failure", start=at(5), end=at(9))]
		get_all = frappe.get_all

		def get_tasks(doctype, *args, **kwargs):
			return tasks if doctype == "Pipeline Task" else get_all(doctype, *args, **kwargs)

		with patch("central.deploy.api.frappe.get_all", side_effect=get_tasks):
			deploy = api.get_deploy_request(self.request.name)
		self.assertEqual(
			(deploy["status"], deploy["error"], deploy["tasks"], deploy["build_log"], deploy["release_log"]),
			("Failed", "DeployBuildError: The build failed.", tasks, "npm ERR\n", ""),
		)
