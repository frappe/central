# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.deploy.agent import DeployAgentError
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest, DeploySupersededError
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.deploy.virtual_machine import DeployMachine
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user


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
		failed.on_pipeline_failure(MagicMock(pipeline_traceback="Traceback\nDeployAgentError: agent is down"))
		self.assertEqual(
			frappe.db.get_value("Deploy Request", failed.name, ["status", "error"]),
			("Failed", "DeployAgentError: agent is down"),
		)

	def test_a_superseded_deploy_stays_superseded_when_its_pipeline_fails(self):
		request = DeployRequest.queue(self.app.name, "a" * 40)
		DeployRequest.queue(self.app.name, "b" * 40)

		request.on_pipeline_failure(MagicMock(pipeline_traceback="DeploySupersededError: superseded"))
		self.assertEqual(self.get_status(request), "Superseded")


class IntegrationTestDeployPipeline(IntegrationTestCase):
	"""A push runs as a pipeline: VM, agent health, then one build."""

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
			}
		).insert()

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
		patch.object(DeployRequest, "wait_for_virtual_machine").start()
		# The repository holds a Dockerfile and, unless a test sets one, no deploy config.
		self.root = [{"name": "Dockerfile", "type": "file"}]
		patch(f"{module}.GitHubDeployApp.list_root", side_effect=lambda *args: self.root).start()
		self.files = {}
		self.get_file = patch(
			f"{module}.GitHubDeployApp.get_file", side_effect=lambda *args: self.files.get(args[3])
		).start()
		patch.object(DeployRequest, "get_build_payload", return_value={"commit": "a" * 40}).start()
		self.agent = patch.object(DeployRequest, "get_agent").start().return_value
		self.agent.start_build.return_value = {"build_id": "build-1"}
		self.addCleanup(patch.stopall)

	def test_a_successful_build_succeeds_the_deploy(self):
		self.agent.get_build.return_value = {"status": "succeeded"}
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value("Deploy Request", request.name, ["status", "agent_build_id"]),
			("Succeeded", "build-1"),
		)
		self.agent.get_health.assert_called_once()
		self.agent.start_build.assert_called_once_with({"commit": "a" * 40})

	def test_only_a_reused_vm_is_resized(self):
		self.agent.get_build.return_value = {"status": "succeeded"}
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

	def test_a_commit_without_a_config_deploys_at_the_default_size(self):
		self.agent.get_build.return_value = {"status": "succeeded"}
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value("Deploy Request", request.name, ["cpu_millicores", "memory_mib", "disk_mib"]),
			(2000, 4096, 20480),
		)
		self.assertIn(
			call("101", "11", "octo/app", "frappe_cloud_deploy.toml", "a" * 40), self.get_file.call_args_list
		)

	def test_the_size_in_the_commits_config_is_saved_on_the_request(self):
		self.agent.get_build.return_value = {"status": "succeeded"}
		self.files["frappe_cloud_deploy.toml"] = "[machine]\ncpu_millicores = 4000\nmemory_mib = 8192\n"
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value("Deploy Request", request.name, ["cpu_millicores", "memory_mib", "disk_mib"]),
			(4000, 8192, 20480),
		)

	def test_a_config_with_an_unknown_machine_key_fails_the_deploy(self):
		self.files["frappe_cloud_deploy.toml"] = '[machine]\nteam = "someone-else"\n'
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(frappe.db.get_value("Deploy Request", request.name, "status"), "Failed")
		self.agent.start_build.assert_not_called()

	def test_a_failed_build_fails_the_deploy_with_the_agents_reason(self):
		self.agent.get_build.return_value = {"status": "failed", "error": "Build ran out of memory."}
		request = DeployRequest.queue(self.app.name, "a" * 40)

		self.assertEqual(
			frappe.db.get_value("Deploy Request", request.name, ["status", "error"]),
			("Failed", "central.deploy.agent.DeployAgentError: Build ran out of memory."),
		)


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
		"""Call `wait` as the agent ping step would, `seconds` after that step started."""
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
					"method_name": "ping_deploy_agent",
					"method_title": "Ping Deploy Agent",
					"signature": frappe.generate_hash(length=16),
				}
			).insert(ignore_permissions=True)

		self.request.flags.current_pipeline_task = task.name
		later = add_to_date(task.creation, seconds=seconds)
		with (
			patch("central.deploy.doctype.deploy_request.deploy_request.now_datetime", return_value=later),
			patch.object(DeployRequest, "defer_current_task") as defer,
		):
			self.request.wait("Agent not answering.", for_=300)
		return defer

	def test_a_step_that_just_started_waits_although_the_deploy_is_old(self):
		self.run_wait_after(10).assert_called_once_with("Agent not answering.")

	def test_a_step_that_waited_too_long_fails(self):
		with self.assertRaises(DeployAgentError):
			self.run_wait_after(400)
