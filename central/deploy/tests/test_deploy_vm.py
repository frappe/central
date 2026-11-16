from unittest.mock import MagicMock, patch

import frappe
import httpx
from frappe.tests import IntegrationTestCase

from central.deploy.agent import DeployAgent
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.deploy.doctype.github_deploy_app_installation.test_github_deploy_app_installation import (
	make_installation,
)
from central.deploy.virtual_machine import AtlasError, DeployMachine
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

TENANT_ID = 7
MODULE = "central.deploy.doctype.deploy_request.deploy_request"


def make_vm(state: str, cpu: int = 2000, memory: int = 4096, disk: int = 20480) -> dict:
	return {
		"current_state": state,
		"compute": {"cpu_millicores": cpu, "memory_mib": memory},
		"disk": {"size_mib": disk},
	}


class IntegrationTestDeployVM(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		team = make_team("Deploy VM Team", ensure_user("deploy.vm.owner@example.test"))
		self.app = frappe.get_doc(
			{
				"doctype": "Deploy App",
				"team": team,
				"installation": make_installation(team).name,
				"repository": "octo/app",
				"repository_id": "11",
				"branch": "main",
				"region": ensure_atlas_instance("deploy-vm-test"),
			}
		).insert()
		with patch.object(DeployRequest, "after_insert"):
			self.request = DeployRequest.queue(self.app.name, "a" * 40)

		self.atlas_vm_id = f"atlas-vm-{frappe.generate_hash(length=8)}"
		self.machine = MagicMock(get_specs=DeployMachine.get_specs)
		self.machine.find.return_value = []
		self.machine.get_newest_image_id.return_value = "image-new"
		self.machine.create.return_value = self.atlas_vm_id
		patch(f"{MODULE}.DeployMachine", return_value=self.machine).start()
		self.wait = patch.object(DeployRequest, "wait").start()
		self.addCleanup(patch.stopall)

	def test_the_first_deploy_creates_a_vm_at_its_size(self):
		self.request.cpu_millicores, self.request.memory_mib = 4000, 8192
		machine = self.request.get_virtual_machine()

		self.assertTrue(machine["is_new"])
		self.machine.create.assert_called_once_with(
			"image-new", {"cpu_millicores": 4000, "memory_mib": 8192, "disk_mib": 20480}
		)
		server = frappe.get_doc("Virtual Machine", machine["name"])
		self.assertEqual((server.atlas_vm_id, server.vcpus), (self.atlas_vm_id, 4))
		self.assertEqual(frappe.db.get_value("Deploy App", self.app.name, "virtual_machine"), server.name)

	def test_a_later_deploy_reuses_the_linked_vm(self):
		first = self.request.get_virtual_machine()
		self.assertEqual(self.request.get_virtual_machine(), {"name": first["name"], "is_new": False})
		self.machine.create.assert_called_once()

	def test_a_vm_atlas_already_built_is_reused_instead_of_created(self):
		self.machine.find.return_value = [{"id": self.atlas_vm_id, "image_id": "image-new"}]

		self.assertFalse(self.request.get_virtual_machine()["is_new"])
		self.machine.create.assert_not_called()

	def test_two_vms_for_one_app_are_refused(self):
		self.machine.find.return_value = [{"id": "atlas-vm-a"}, {"id": "atlas-vm-b"}]

		with self.assertRaises(frappe.ValidationError):
			self.request.get_virtual_machine()
		self.machine.create.assert_not_called()

	def test_a_region_without_a_deploy_image_is_refused(self):
		self.machine.get_newest_image_id.return_value = None

		with self.assertRaises(frappe.ValidationError):
			self.request.get_virtual_machine()

	def test_a_vm_at_the_deploys_size_is_left_alone(self):
		name = self.request.get_virtual_machine()["name"]
		self.machine.get.return_value = make_vm("running")

		self.request.resize_virtual_machine(name)
		self.machine.stop.assert_not_called()
		self.machine.resize.assert_not_called()
		self.wait.assert_not_called()

	def test_a_new_size_stops_then_resizes_then_starts_the_vm(self):
		name = self.request.get_virtual_machine()["name"]
		self.request.cpu_millicores, self.request.memory_mib = 4000, 8192

		self.machine.get.return_value = make_vm("running")
		self.request.resize_virtual_machine(name)
		self.machine.stop.assert_called_once_with(self.atlas_vm_id)

		self.machine.get.return_value = make_vm("stopped")
		self.request.resize_virtual_machine(name)
		self.machine.resize.assert_called_once_with(
			self.atlas_vm_id, {"cpu_millicores": 4000, "memory_mib": 8192, "disk_mib": 20480}
		)

		self.machine.get.return_value = make_vm("migrating", cpu=4000, memory=8192)
		self.wait.reset_mock()
		self.request.resize_virtual_machine(name)
		self.wait.assert_called_once()

		self.machine.get.return_value = make_vm("stopped", cpu=4000, memory=8192)
		self.request.resize_virtual_machine(name)
		self.machine.start.assert_called_once_with(self.atlas_vm_id)

	def test_a_smaller_disk_is_refused(self):
		name = self.request.get_virtual_machine()["name"]
		self.request.disk_mib = 10240
		self.machine.get.return_value = make_vm("running")

		with self.assertRaises(frappe.ValidationError):
			self.request.resize_virtual_machine(name)
		self.machine.stop.assert_not_called()

	def test_the_agent_is_called_on_the_mesh_address_with_a_central_token(self):
		server = MagicMock(ipv6_address="fd00::7")
		server.name = "server-deploy-x"
		with (
			patch("central.deploy.agent.mint_deploy_agent_token", return_value="token") as mint,
			patch("central.deploy.agent.requests.request") as request,
		):
			request.return_value = MagicMock(ok=True, json=MagicMock(return_value={"build_id": "b1"}))
			self.assertEqual(DeployAgent(server).start_build({"commit": "a" * 40}), {"build_id": "b1"})

		mint.assert_called_once_with("server-deploy-x")
		method, url = request.call_args.args
		self.assertEqual((method, url), ("POST", "http://[fd00::7]:7070/builds"))
		self.assertEqual(request.call_args.kwargs["headers"], {"Authorization": "Bearer token"})


class IntegrationTestDeployMachine(IntegrationTestCase):
	def setUp(self):
		region = MagicMock(base_url="https://atlas.test/", get_atlas_region_id=MagicMock(return_value=1))
		with (
			patch("central.deploy.virtual_machine.frappe.get_cached_doc", return_value=region),
			patch("central.deploy.virtual_machine.frappe.db.get_value", return_value=TENANT_ID),
			patch("central.deploy.virtual_machine.mint_atlas_token", return_value="token"),
		):
			self.machine = DeployMachine(frappe._dict(name="deploy-app-1", team="team-1", region="region-1"))
		self.request = patch.object(self.machine.client.get_httpx_client(), "request").start()
		self.addCleanup(patch.stopall)

	def answer(self, status: int, body: dict) -> None:
		self.request.return_value = httpx.Response(status, json=body)

	def test_only_this_tenants_vms_with_this_apps_tags_are_found(self):
		tags = {"purpose": "deploy", "deploy_app": "deploy-app-1"}
		self.answer(
			200,
			{
				"items": [
					{"id": "mine", "tenant_id": TENANT_ID, "tags": tags},
					{"id": "other-tenant", "tenant_id": 8, "tags": tags},
					{"id": "other-app", "tenant_id": TENANT_ID, "tags": {**tags, "deploy_app": "x"}},
				]
			},
		)

		self.assertEqual([vm["id"] for vm in self.machine.find()], ["mine"])
		request = self.request.call_args.kwargs
		self.assertEqual(request["params"]["tag"], "purpose:deploy,deploy_app:deploy-app-1")
		self.assertEqual(request["headers"]["X-Tenant-ID"], str(TENANT_ID))

	def test_a_failed_call_raises_atlas_error(self):
		self.answer(503, {"error": {"message": "busy"}})

		with self.assertRaises(AtlasError):
			self.machine.get("vm-1")
