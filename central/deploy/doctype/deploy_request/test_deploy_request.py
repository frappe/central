# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.deploy.doctype.deploy_request.deploy_request import (
	BUILD_REPORT_TIMEOUT_SECONDS,
	DeployRequest,
	DeploySupersededError,
	DeployTimeoutError,
)
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.deploy.tests.test_deploy_billing import catalog, make_size
from central.deploy.virtual_machine import DeployMachine
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region


class IntegrationTestDeployRequest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Only the rows matter here; the deploy pipeline is not started.
		patch.object(DeployRequest, "after_insert").start()
		self.addCleanup(patch.stopall)
		team = make_team("Deploy Request Team", ensure_user("deploy.request.owner@example.test"))
		self.app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team).name,
				"repository": "octo/app",
				"repository_id": "11",
				"branch": "main",
			}
		).insert()

	def get_status(self, request: DeployRequest) -> str:
		return frappe.db.get_value("Deploy Request", request.name, "status")

	def set_status(self, request: DeployRequest, status: str) -> None:
		request.status = status
		request.save()

	def test_a_newer_push_supersedes_a_queued_or_building_deploy(self):
		queued = DeployRequest.queue(self.app.name, "a" * 40)
		building = DeployRequest.queue(self.app.name, "b" * 40)
		self.set_status(building, "Building")
		newest = DeployRequest.queue(self.app.name, "c" * 40)

		self.assertEqual((self.get_status(queued), self.get_status(building)), ("Superseded", "Superseded"))
		self.assertEqual((newest.status, newest.team), ("Queued", self.app.team))

	def test_a_release_is_never_superseded(self):
		releasing = DeployRequest.queue(self.app.name, "a" * 40)
		self.set_status(releasing, "Releasing")
		DeployRequest.queue(self.app.name, "b" * 40)

		self.assertEqual(self.get_status(releasing), "Releasing")

	def test_a_superseded_deploy_stops_at_its_next_step(self):
		request = DeployRequest.queue(self.app.name, "a" * 40)
		DeployRequest.queue(self.app.name, "b" * 40)

		with self.assertRaises(DeploySupersededError):
			request.set_status("Building")
		self.assertEqual(self.get_status(request), "Superseded")

	def test_a_finished_pipeline_sets_the_outcome(self):
		succeeded = DeployRequest.queue(self.app.name, "a" * 40)
		succeeded.on_pipeline_success(MagicMock())
		self.assertEqual(self.get_status(succeeded), "Succeeded")

		failed = DeployRequest.queue(self.app.name, "b" * 40)
		failed.on_pipeline_failure(
			MagicMock(pipeline_traceback="Traceback\nDeployBuildError: The build failed.")
		)
		self.assertEqual(
			frappe.db.get_value("Deploy Request", failed.name, ["status", "error"]),
			("Failed", "DeployBuildError: The build failed."),
		)

	def test_a_superseded_deploy_stays_superseded_when_its_pipeline_fails(self):
		request = DeployRequest.queue(self.app.name, "a" * 40)
		DeployRequest.queue(self.app.name, "b" * 40)

		request.on_pipeline_failure(MagicMock(pipeline_traceback="DeploySupersededError: superseded"))
		self.assertEqual(self.get_status(request), "Superseded")


class IntegrationTestDeployPipeline(IntegrationTestCase):
	"""A push runs as a pipeline: VM, then a build the deploy agent reports on."""

	def setUp(self):
		frappe.set_user("Administrator")
		team = make_team("Deploy Pipeline Team", ensure_user("deploy.pipeline.owner@example.test"))
		self.app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team).name,
				"repository": "octo/app",
				"repository_id": "11",
				"branch": "main",
				"region": ensure_region("deploy-pipeline-test"),
			}
		).insert()
		self.growth, self.pro = make_size("Growth", 2, 8, 100), make_size("Pro", 4, 16, 200)
		patch(
			"central.deploy.billing.get_server_plans",
			return_value=catalog((self.growth, "Growth"), (self.pro, "Pro")),
		).start()

		module = "central.deploy.doctype.deploy_request.deploy_request"
		self.find_or_create = patch.object(
			DeployRequest,
			"find_or_create_virtual_machine",
			return_value={"name": "server-deploy-test", "is_new": True},
		).start()
		# The real step runs, so the pipeline records it once however often the flow replays.
		self.machine = patch(f"{module}.DeployMachine").start().return_value
		self.machine.get.return_value = {
			"current_state": "running",
			"compute": {"cpu_millicores": 2000, "memory_mib": 4096},
			"disk": {"size_mib": 20480},
		}
		self.machine.get_specs = DeployMachine.get_specs
		# The deploy agent reports while the VM step runs; None means the agent has not reported yet.
		self.build_status = "Succeeded"
		patch.object(DeployRequest, "wait_for_virtual_machine", side_effect=self.report_build).start()
		# The repository holds a Dockerfile and, unless a test sets one, no deploy config.
		self.root = [{"name": "Dockerfile", "type": "file"}]
		patch(f"{module}.GitHubDeployApp.list_root", side_effect=lambda *args: self.root).start()
		self.files = {}
		self.get_file = patch(
			f"{module}.GitHubDeployApp.get_file", side_effect=lambda *args: self.files.get(args[3])
		).start()
		self.addCleanup(patch.stopall)

	def report_build(self, virtual_machine: str) -> None:
		if self.build_status:
			doc = frappe.get_last_doc("Deploy Request", filters={"deploy_app": self.app.name})
			doc.build_status = self.build_status
			doc.save()

	def test_a_successful_build_succeeds_the_deploy(self):
		request = DeployRequest.queue(self.app.name, "a" * 40)
		self.assertEqual(frappe.db.get_value("Deploy Request", request.name, "status"), "Succeeded")

	def test_a_build_no_agent_finished_keeps_the_deploy_building(self):
		self.build_status = None
		request = DeployRequest.queue(self.app.name, "a" * 40)
		self.assertEqual(frappe.db.get_value("Deploy Request", request.name, "status"), "Building")

	def test_only_a_reused_vm_is_resized(self):
		DeployRequest.queue(self.app.name, "a" * 40)
		self.machine.get.assert_not_called()

		self.find_or_create.return_value = {"name": "server-deploy-test", "is_new": False}
		DeployRequest.queue(self.app.name, "b" * 40)
		self.machine.get.assert_called_once()

	def test_a_commit_without_a_dockerfile_fails_before_a_vm_is_touched(self):
		self.root = [{"name": "README.md", "type": "file"}]
		request = DeployRequest.queue(self.app.name, "a" * 40)

		status, error = frappe.db.get_value("Deploy Request", request.name, ["status", "error"])
		self.assertEqual(status, "Failed")
		self.assertIn("Add a Dockerfile", error)
		self.find_or_create.assert_not_called()

	def test_a_commit_without_a_config_deploys_at_growth(self):
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value(
				"Deploy Request", request.name, ["plan", "cpu_millicores", "memory_mib", "disk_mib"]
			),
			(self.growth, 2000, 8192, 102400),
		)
		self.assertIn(
			call("101", "11", "octo/app", "frappe_cloud_deploy.toml", "a" * 40), self.get_file.call_args_list
		)

	def test_the_size_in_the_commits_config_is_saved_on_the_request(self):
		self.files["frappe_cloud_deploy.toml"] = '[machine]\nsize = "Pro"\n'
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value(
				"Deploy Request", request.name, ["plan", "cpu_millicores", "memory_mib", "disk_mib"]
			),
			(self.pro, 4000, 16384, 204800),
		)

	def test_a_size_that_is_not_for_sale_fails_the_deploy(self):
		self.files["frappe_cloud_deploy.toml"] = '[machine]\nsize = "Huge"\n'
		request = DeployRequest.queue(self.app.name, "a" * 40)

		status, error = frappe.db.get_value("Deploy Request", request.name, ["status", "error"])
		self.assertEqual(status, "Failed")
		self.assertIn("Growth, Pro", error)
		self.find_or_create.assert_not_called()

	def test_a_config_with_an_unknown_machine_key_fails_the_deploy(self):
		self.files["frappe_cloud_deploy.toml"] = '[machine]\nteam = "someone-else"\n'
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(frappe.db.get_value("Deploy Request", request.name, "status"), "Failed")
		self.find_or_create.assert_not_called()

	def test_a_failed_build_fails_the_deploy(self):
		self.build_status = "Failed"
		request = DeployRequest.queue(self.app.name, "a" * 40)

		status, error = frappe.db.get_value("Deploy Request", request.name, ["status", "error"])
		self.assertEqual(status, "Failed")
		self.assertIn("DeployBuildError: The build failed. See its log.", error)


class IntegrationTestDeployWait(IntegrationTestCase):
	"""A step waits from when it started, not from when the push arrived."""

	def setUp(self):
		frappe.set_user("Administrator")
		team = make_team("Deploy Wait Team", ensure_user("deploy.wait.owner@example.test"))
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
		with patch.object(DeployRequest, "after_insert"):
			self.request = DeployRequest.queue(app.name, "a" * 40)
		self.request.creation = add_to_date(now_datetime(), hours=-1)

	def run_wait_after(self, seconds: int) -> MagicMock:
		"""Call `wait` as the build step would, `seconds` after that step started."""
		with (
			patch("cloudtoolkit.pipeline.doctype.pipeline.pipeline.enqueue_pipeline"),
			patch("cloudtoolkit.pipeline.doctype.pipeline_task.pipeline_task.enqueue_task"),
		):
			pipeline = frappe.get_doc(
				{
					"doctype": "Pipeline",
					"linked_doctype": "Deploy Request",
					"linked_docname": self.request.name,
					"main_method_name": "start_deploy",
					"main_method_title": "Start Deploy",
				}
			).insert(ignore_permissions=True)
			task = frappe.get_doc(
				{
					"doctype": "Pipeline Task",
					"pipeline": pipeline.name,
					"method_name": "wait_for_build",
					"method_title": "Wait For Build",
					"signature": frappe.generate_hash(length=16),
				}
			).insert(ignore_permissions=True)

		self.request.flags.current_pipeline_task = task.name
		later = add_to_date(task.creation, seconds=seconds)
		with (
			patch("central.deploy.doctype.deploy_request.deploy_request.now_datetime", return_value=later),
			patch.object(DeployRequest, "defer_current_task") as defer,
		):
			self.request.wait("Build not finished.", for_=300)
		return defer

	def test_a_step_that_just_started_waits_although_the_deploy_is_old(self):
		self.run_wait_after(10).assert_called_once_with("Build not finished.")

	def test_a_step_that_waited_too_long_fails(self):
		with self.assertRaises(DeployTimeoutError):
			self.run_wait_after(400)

	def test_an_agent_that_reported_recently_is_not_silent(self):
		self.assertFalse(self.request.is_silent(add_to_date(now_datetime(), seconds=-10)))

	def test_an_agent_that_stopped_reporting_is_silent(self):
		self.assertTrue(
			self.request.is_silent(add_to_date(now_datetime(), seconds=-BUILD_REPORT_TIMEOUT_SECONDS - 1))
		)

	def test_an_agent_that_never_reported_is_silent_once_the_step_waited_too_long(self):
		self.assertTrue(self.request.is_silent(None))
