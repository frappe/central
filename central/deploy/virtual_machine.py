from __future__ import annotations

import json
from types import ModuleType
from typing import TYPE_CHECKING, Any

import frappe
import httpx
from atlas_client import AuthenticatedClient
from atlas_client.api.images import list_images
from atlas_client.api.vm_actions import resize_virtual_machine, start_virtual_machine, stop_virtual_machine
from atlas_client.api.vm_lifecycle import create_virtual_machine, get_virtual_machine, list_virtual_machines
from atlas_client.models import CreateVirtualMachinePayload, ListImagesImageTypeType0, ResizePayload
from frappe import _

from central.infrastructure.doctype.virtual_machine import firewall
from central.sso import central_url, mint_atlas_token

if TYPE_CHECKING:
	from central.deploy.doctype.deploy_app.deploy_app import DeployApp

DEPLOY_IMAGE_TAG = "purpose:deploy"
# The deploy agent reads this guest metadata key. Matches cargo/image_builder/conf/build_agent.
AGENT_METADATA_KEY = "deploy-agent"
# The most a list route returns in one page.
PAGE_LIMIT = 100


class AtlasError(RuntimeError):
	"""An Atlas call failed. One argument, so the pipeline engine can pickle it."""


class DeployMachine:
	"""The Atlas VM of one Deploy App, through the generated `atlas_client`. Returns what Atlas
	says and raises only `AtlasError`; the Deploy Request decides what the answers mean."""

	def __init__(self, app: DeployApp) -> None:
		region = frappe.get_cached_doc("Region", app.region)
		self.app = app
		self.tenant_id = frappe.db.get_value("Team", app.team, "tenant_id")
		self.client = AuthenticatedClient(
			base_url=region.base_url.rstrip("/"),
			token=mint_atlas_token(region.get_atlas_region_id()),
			timeout=httpx.Timeout(20, connect=5),
		)

	@property
	def tags(self) -> dict[str, str]:
		"""Set on the VM at create, so a create whose reply was lost is found again."""
		return {"purpose": "deploy", "deploy_app": self.app.name}

	def find(self) -> list[dict]:
		"""Every live VM of this tenant that carries this app's tags."""
		tag = ",".join(f"{key}:{value}" for key, value in self.tags.items())
		page = self.call(list_virtual_machines, tag=tag, limit=2)
		return [
			vm
			for vm in page.get("items") or []
			# Checked here too, so a region that ignored the filter cannot hand over another VM.
			if vm.get("tenant_id") == self.tenant_id
			and self.tags.items() <= (vm.get("tags") or {}).items()
			and vm.get("last_known_state") != "terminating"
		]

	def get_newest_image_id(self) -> str | None:
		"""The newest available deploy image of the region. Atlas lists images newest first."""
		page = self.call(
			list_images, image_type=ListImagesImageTypeType0.SYSTEM, tag=DEPLOY_IMAGE_TAG, limit=PAGE_LIMIT
		)
		images = page.get("items") or []
		return next((image["id"] for image in images if image.get("status") == "available"), None)

	def create(self, image_id: str, specs: dict[str, int]) -> str:
		"""Ask Atlas for the VM once and return its id. Never retried: the caller runs `find` first."""
		settings = frappe.get_cached_doc("Central Settings")
		payload = {
			"image_id": image_id,
			**specs,
			"disk_iops": settings.disk_iops,
			"disk_throughput_mibps": settings.disk_throughput_mibps,
			"private_network_throughput_mibps": settings.private_network_throughput_mibps,
			"public_network_throughput_mibps": settings.public_network_throughput_mibps,
			"firewall": firewall.get_new_server_firewall(True),
			"tags": self.tags,
			"metadata": self.metadata,
		}
		created = self.call(create_virtual_machine, body=CreateVirtualMachinePayload.from_dict(payload))
		if not isinstance(created, dict) or not created.get("id"):
			raise AtlasError(_("Atlas created a VM but returned no ID."))
		return created["id"]

	@property
	def metadata(self) -> dict[str, str]:
		"""Guest metadata that gives the VM's deploy agent where Central is and the app's credential."""
		agent = {
			"central_url": central_url(),
			"credential": f"{self.app.name}:{self.app.get_password('agent_token')}",
		}
		return {AGENT_METADATA_KEY: json.dumps(agent)}

	def get(self, vm_id: str) -> dict:
		"""The VM as Atlas sees it now, with `current_state`, `compute` and `disk`."""
		return self.call(get_virtual_machine, vm_id)

	def start(self, vm_id: str) -> None:
		self.call(start_virtual_machine, vm_id)

	def stop(self, vm_id: str) -> None:
		self.call(stop_virtual_machine, vm_id)

	def resize(self, vm_id: str, specs: dict[str, int]) -> None:
		"""Atlas resizes only a stopped VM, may move it to another host meanwhile, and never shrinks the disk."""
		self.call(resize_virtual_machine, vm_id, body=ResizePayload(**specs))

	@staticmethod
	def get_specs(vm: dict) -> dict[str, int]:
		"""The size Atlas reports for a VM, keyed like a Deploy Request's specs."""
		compute, disk = vm.get("compute") or {}, vm.get("disk") or {}
		return {
			"cpu_millicores": compute.get("cpu_millicores"),
			"memory_mib": compute.get("memory_mib"),
			"disk_mib": disk.get("size_mib"),
		}

	def call(self, endpoint: ModuleType, *args: Any, **kwargs: Any) -> Any:
		"""One request built by a generated endpoint, returning the JSON body.

		The body is read as JSON, not parsed by the endpoint: a strict parse that fails after Atlas
		created a VM would read as a failed create."""
		name = endpoint.__name__.rsplit(".", 1)[-1]
		request = endpoint._get_kwargs(*args, x_tenant_id=self.tenant_id, **kwargs)
		try:
			response = self.client.get_httpx_client().request(**request)
		except httpx.HTTPError as error:
			raise AtlasError(_("Atlas could not be reached for {0}: {1}").format(name, str(error))) from error

		if not response.is_success:
			raise AtlasError(
				_("Atlas answered {0} with HTTP {1}: {2}").format(
					name, response.status_code, response.text[:500]
				)
			)
		return response.json() if response.content else None
