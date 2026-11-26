import json
from unittest.mock import MagicMock, patch

import frappe
import httpx
from frappe.tests import IntegrationTestCase

from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.deploy.tests.test_deploy_billing import make_size
from central.deploy.virtual_machine import AtlasError, DeployMachine
from central.infrastructure.doctype.github_connection.test_github_connection import make_team
from central.infrastructure.doctype.github_installation.test_github_installation import (
	make_installation,
)
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
		self.request.plan = make_size("Growth", 2, 8, 100)

		self.atlas_vm_id = f"atlas-vm-{frappe.generate_hash(length=8)}"
		self.machine = MagicMock(get_specs=DeployMachine.get_specs)
		self.machine.find.return_value = []
		self.machine.get_newest_image_id.return_value = "image-new"
		self.machine.create.return_value = self.atlas_vm_id
		self.machine.get.return_value = make_vm("running", memory=8192, disk=102400)
		patch(f"{MODULE}.DeployMachine", return_value=self.machine).start()
		self.observe = patch(f"{MODULE}.servers.observe_server", return_value="Running").start()
		self.wait = patch.object(DeployRequest, "wait").start()
		self.validate_purchase = patch(f"{MODULE}.validate_vm_purchase", return_value=12.5).start()
		self.open_subscription = patch(f"{MODULE}.open_vm_subscription").start()
		self.begin_resize = patch(f"{MODULE}.begin_resize", return_value={"queued": False}).start()
		self.addCleanup(patch.stopall)

	def link_vm(self) -> str:
		return self.request.find_or_create_virtual_machine(self.app)

	def test_the_first_deploy_creates_a_vm_at_its_plans_size(self):
		server = frappe.get_doc("Virtual Machine", self.link_vm())

		self.machine.create.assert_called_once_with(
			"image-new", {"cpu_millicores": 2000, "memory_mib": 8192, "disk_mib": 102400}
		)
		self.assertEqual(
			(server.atlas_vm_id, server.plan, server.vcpus), (self.atlas_vm_id, self.request.plan, 2)
		)
		self.assertEqual(frappe.db.get_value("Deploy App", self.app.name, "virtual_machine"), server.name)
		self.validate_purchase.assert_called_once_with(self.app.team, self.app.region, self.request.plan)
		self.open_subscription.assert_called_once_with(
			server.name, self.app.team, self.app.region, plan=self.request.plan, rate=12.5
		)

	def test_a_purchase_billing_refuses_creates_no_vm(self):
		self.validate_purchase.side_effect = frappe.ValidationError

		with self.assertRaises(frappe.ValidationError):
			self.link_vm()
		self.machine.create.assert_not_called()
		self.open_subscription.assert_not_called()

	def test_a_later_deploy_reuses_the_linked_vm(self):
		first = self.link_vm()
		self.assertEqual(self.link_vm(), first)
		self.machine.create.assert_called_once()

	def test_a_vm_from_a_lost_create_is_billed_at_the_size_atlas_reports(self):
		self.machine.find.return_value = [{"id": self.atlas_vm_id, "image_id": "image-new"}]
		self.machine.get.return_value = make_vm("running", cpu=1000, memory=2048, disk=25600)

		server = frappe.get_doc("Virtual Machine", self.link_vm())

		self.machine.create.assert_not_called()
		self.validate_purchase.assert_not_called()
		self.assertIsNone(server.plan)
		self.assertEqual((server.vcpus, server.memory_megabytes, server.disk_gigabytes), (1, 2048, 25))
		self.open_subscription.assert_called_once_with(
			server.name,
			self.app.team,
			self.app.region,
			includes=[
				{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 2, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 25, "unit": "GB"},
			],
		)

	def test_a_deploy_after_termination_records_the_new_vm_as_a_new_server(self):
		old = self.link_vm()
		# What termination leaves: a Terminated row, and an app no longer linked to it.
		frappe.db.set_value("Virtual Machine", old, "status", "Terminated")
		self.app.reload()
		self.app.virtual_machine = None
		self.machine.create.return_value = new_atlas_vm_id = f"atlas-vm-{frappe.generate_hash(length=8)}"

		new = self.link_vm()

		self.assertNotEqual(new, old)
		self.assertEqual(frappe.db.get_value("Virtual Machine", new, "atlas_vm_id"), new_atlas_vm_id)
		self.assertEqual(frappe.db.get_value("Deploy App", self.app.name, "virtual_machine"), new)
		self.assertEqual(
			frappe.db.get_value("Virtual Machine", old, ["status", "atlas_vm_id"]),
			("Terminated", self.atlas_vm_id),
		)

	def test_two_vms_for_one_app_are_refused(self):
		self.machine.find.return_value = [{"id": "atlas-vm-a"}, {"id": "atlas-vm-b"}]

		with self.assertRaises(frappe.ValidationError):
			self.link_vm()
		self.machine.create.assert_not_called()

	def test_a_region_without_a_deploy_image_is_refused(self):
		self.machine.get_newest_image_id.return_value = None

		with self.assertRaises(frappe.ValidationError):
			self.link_vm()

	def test_a_running_vm_at_the_plans_size_records_that_size(self):
		self.link_vm()

		self.request.converge_virtual_machine()
		self.begin_resize.assert_called_once_with(None, plan=self.request.plan, disk_gigabytes=100)
		self.wait.assert_not_called()
		self.assertEqual(
			(self.request.cpu_millicores, self.request.memory_mib, self.request.disk_mib),
			(2000, 8192, 102400),
		)

	def test_a_vm_still_provisioning_is_waited_on_without_a_resize(self):
		self.link_vm()
		self.observe.return_value = "Provisioning"

		self.request.converge_virtual_machine()
		self.wait.assert_called_once()
		self.begin_resize.assert_not_called()
		self.assertFalse(self.request.disk_mib)

	def test_a_stopped_vm_is_started_and_waited_on(self):
		self.link_vm()
		self.observe.return_value = "Stopped"

		self.request.converge_virtual_machine()
		self.machine.start.assert_called_once_with(self.atlas_vm_id)
		self.wait.assert_called_once()

	def test_a_migrating_vm_is_waited_on(self):
		self.link_vm()
		self.machine.get.return_value = make_vm("migrating")

		self.request.converge_virtual_machine()
		self.wait.assert_called_once()
		self.observe.assert_not_called()

	def test_a_new_size_waits_for_the_consoles_resize_before_recording_a_size(self):
		self.link_vm()
		self.begin_resize.return_value = {"queued": True}

		self.request.converge_virtual_machine()
		self.wait.assert_called_once()
		self.machine.start.assert_not_called()
		self.assertFalse(self.request.disk_mib)

	def test_a_resize_still_running_is_waited_on_without_a_new_one(self):
		self.make_resize(self.link_vm(), "Sent")

		self.request.converge_virtual_machine()
		self.wait.assert_called_once()
		self.begin_resize.assert_not_called()

	def test_a_failed_resize_fails_the_deploy_with_its_error(self):
		self.make_resize(self.link_vm(), "Failed", error_code="ACTION_FAILED")

		with self.assertRaisesRegex(frappe.ValidationError, "reported a failure while trying to resize"):
			self.request.converge_virtual_machine()
		self.begin_resize.assert_not_called()

	def test_a_resize_billing_refuses_fails_the_deploy(self):
		self.link_vm()
		self.begin_resize.side_effect = frappe.ValidationError

		with self.assertRaises(frappe.ValidationError):
			self.request.converge_virtual_machine()
		self.machine.start.assert_not_called()

	def test_a_plan_with_a_smaller_disk_keeps_the_vms_disk_and_says_so(self):
		self.link_vm()
		self.machine.get.return_value = make_vm("running", memory=8192, disk=204800)

		self.request.converge_virtual_machine()
		self.request.converge_virtual_machine()
		self.begin_resize.assert_called_with(None, plan=self.request.plan, disk_gigabytes=200)
		self.assertEqual(frappe.db.get_value("Deploy Request", self.request.name, "disk_mib"), 204800)
		self.assertEqual(self.request.get_log("build_log").count("Preserving disk size"), 1)

	def make_resize(self, server: str, status: str, **fields) -> None:
		frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "resize",
				"team": self.app.team,
				"server": server,
				"status": status,
				**fields,
			}
		).insert(ignore_permissions=True)


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

	def test_a_terminating_vm_is_not_found(self):
		tags = {"purpose": "deploy", "deploy_app": "deploy-app-1"}
		self.answer(
			200,
			{
				"items": [
					{"id": "new", "tenant_id": TENANT_ID, "tags": tags, "last_known_state": "running"},
					{"id": "old", "tenant_id": TENANT_ID, "tags": tags, "last_known_state": "terminating"},
				]
			},
		)

		self.assertEqual([vm["id"] for vm in self.machine.find()], ["new"])

	def test_the_metadata_gives_the_agent_central_and_its_credential(self):
		self.machine.app = MagicMock(get_password=MagicMock(return_value="secret"))
		self.machine.app.name = "deploy-app-1"
		with patch("central.deploy.virtual_machine.central_url", return_value="https://central.test"):
			metadata = self.machine.metadata

		self.assertEqual(
			json.loads(metadata["deploy-agent"]),
			{"central_url": "https://central.test", "credential": "deploy-app-1:secret"},
		)

	def test_a_failed_call_raises_atlas_error(self):
		self.answer(503, {"error": {"message": "busy"}})

		with self.assertRaises(AtlasError):
			self.machine.get("vm-1")
