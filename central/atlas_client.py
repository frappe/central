from __future__ import annotations

import frappe
import requests

# Edge B: Central → regional Atlas. Authenticated with the per-region API
# key/secret stored on the `Atlas Instance` record (frappe token auth). The
# inventory sync (#27) and the billing push both call Atlas through this client.

REQUEST_TIMEOUT = 30


class AtlasError(frappe.ValidationError):
	pass


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
