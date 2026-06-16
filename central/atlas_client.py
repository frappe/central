from __future__ import annotations

import frappe
import requests

# Edge B: Central → regional Atlas. Authenticated with the per-region API
# key/secret stored on the `Atlas Instance` record (frappe token auth). The
# inventory sync (#27) and the billing push both call Atlas through this client.

REQUEST_TIMEOUT = 30

# Frozen inventory contract Atlas fulfils (#36) and Central mirrors into Asset rows
# (#20/#27). One dict per VM:
INVENTORY_VM_FIELDS = ("resource_id", "status", "gateway_url")


class AtlasError(frappe.ValidationError):
	pass


def stub_vm_inventory(team: str) -> list[dict]:
	"""Canned inventory in INVENTORY_VM_FIELDS shape — used by the dev sync until
	Atlas ships the real endpoint (#36). Keeps Central buildable against a fake."""
	return [
		{"resource_id": "vm-blr-1", "status": "Running", "gateway_url": "http://localhost:3030"},
		{"resource_id": "vm-blr-2", "status": "Stopped", "gateway_url": ""},
	]


def get_atlas_instance(region: str):
	"""Resolve a region (= cluster) to its `Atlas Instance`, or raise."""
	name = frappe.db.get_value("Atlas Instance", {"region": region})
	if not name:
		frappe.throw(f"No Atlas registered for region '{region}'.", AtlasError)
	return frappe.get_doc("Atlas Instance", name)


class AtlasClient:
	"""Thin authenticated HTTP client for one regional Atlas."""

	def __init__(self, instance):
		self.instance = instance

	@classmethod
	def for_region(cls, region: str) -> "AtlasClient":
		return cls(get_atlas_instance(region))

	def _headers(self) -> dict:
		secret = self.instance.get_password("api_secret")
		return {"Authorization": f"token {self.instance.api_key}:{secret}"}

	def _url(self, path: str) -> str:
		return f"{self.instance.base_url.rstrip('/')}/{path.lstrip('/')}"

	def request(self, method: str, path: str, **kwargs) -> dict:
		if self.instance.status == "Disabled":
			frappe.throw(f"Atlas '{self.instance.region}' is disabled.", AtlasError)
		resp = requests.request(
			method, self._url(path), headers=self._headers(), timeout=REQUEST_TIMEOUT, **kwargs
		)
		resp.raise_for_status()
		return resp.json()

	def ping(self) -> dict:
		"""Cheap reachability + auth check against the frappe ping endpoint."""
		return self.request("GET", "/api/method/ping")

	def list_vms(self, team: str) -> list[dict]:
		"""Inventory of a team's VMs in this cluster — the registry mirror source.

		Atlas (#36) returns one dict per VM in INVENTORY_VM_FIELDS: `resource_id`,
		`status` (Provisioning/Running/Stopped/Terminated), `gateway_url` (set only
		when Running). The cluster/region is implied by this Atlas Instance, and
		`team` scopes the result server-side.
		"""
		return self.request("GET", "/api/method/atlas.api.list_team_vms", params={"team": team})
