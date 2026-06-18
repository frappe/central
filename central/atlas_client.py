from __future__ import annotations

import frappe
from frappe.frappeclient import FrappeClient

# Edge B: Central → regional Atlas, over Frappe's standard FrappeClient. Token
# auth uses the per-instance API key/secret on the `Atlas Instance` record.


class AtlasError(frappe.ValidationError):
	pass


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

	def central_vms(self, central_reference: str | None = None) -> list[dict]:
		"""Tenant-tagged VMs on this Atlas for the mirror reconcile (optionally one
		team). One dict per VM: name, central_reference, status, gateway_url."""
		params = {"central_reference": central_reference} if central_reference else None
		return self.client().get_api("atlas.atlas.api.inventory.tenant_vms", params)
