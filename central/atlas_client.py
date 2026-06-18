from __future__ import annotations

import frappe
from frappe.frappeclient import FrappeClient

# Frozen inventory contract Atlas fulfils and Central mirrors into Asset rows.
INVENTORY_VM_FIELDS = ("resource_id", "status", "gateway_url")


class AtlasError(frappe.ValidationError):
	pass


def stub_vm_inventory(team: str) -> list[dict]:
	"""Canned inventory in INVENTORY_VM_FIELDS shape — used by the dev sync until
	Atlas ships the real endpoint. Keeps Central buildable against a fake."""
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
	"""A FrappeClient bound to one regional Atlas, built from its Atlas Instance."""

	def __init__(self, instance):
		self.instance = instance

	@classmethod
	def for_region(cls, region: str) -> "AtlasClient":
		return cls(get_atlas_instance(region))

	def client(self) -> FrappeClient:
		if self.instance.status == "Disabled":
			frappe.throw(f"Atlas '{self.instance.region}' is disabled.", AtlasError)
		return FrappeClient(
			self.instance.base_url,
			api_key=self.instance.api_key,
			api_secret=self.instance.get_password("api_secret"),
		)

	def ping(self) -> dict:
		"""Reachability + auth check against the frappe ping endpoint."""
		return self.client().get_api("ping")

	def vm_action(self, name: str, method: str) -> str:
		"""Invoke a Virtual Machine lifecycle method (start/stop/terminate) as the
		operator; return the resulting Task name."""
		return self.client().post_api(
			"run_doc_method", params={"dt": "Virtual Machine", "dn": name, "method": method}
		)

	def list_vms(self, team: str) -> list[dict]:
		"""Inventory of a team's VMs in this cluster — the registry mirror source."""
		return self.client().get_api("atlas.api.list_team_vms", {"team": team})
