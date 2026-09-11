from __future__ import annotations

from functools import cached_property

import frappe
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password

TOKEN_HEADER = "X-Cargo-Access-Token"
BUCKET_API = "cargo.object_storage.api.bucket"
TIMEOUT = 60


class CargoClient:
	"""Central's half of the bucket API. Cargo mints and holds the cluster's admin token, so
	every bucket operation is proxied to the region's host instead of run against Garage."""

	def __init__(self, region: str) -> None:
		self.region = region

	@cached_property
	def instance(self) -> frappe._dict:
		instance = frappe.db.get_value(
			"Cargo Instance",
			{"region": self.region, "status": "Registered"},
			["name", "base_url"],
			as_dict=True,
		)
		if not instance or not instance.base_url:
			frappe.throw(_("No registered Cargo host serves {0}.").format(self.region))

		return instance

	@cached_property
	def token(self) -> str:
		token = get_decrypted_password(
			"Cargo Instance", self.instance.name, "cargo_access_token", raise_exception=False
		)
		if not token:
			frappe.throw(_("The Cargo host for {0} has no access token yet.").format(self.region))

		return token

	def create_bucket(self, bucket: str) -> dict:
		"""The bucket and the one key that opens it. Cargo hands the secret back once."""
		return self._call("create_bucket", bucket)["credentials"]

	def delete_bucket(self, bucket: str) -> None:
		self._call("delete_bucket", bucket)

	def rotate_credentials(self, bucket: str) -> dict:
		return self._call("rotate_credentials", bucket)["credentials"]

	def revoke_credentials(self, bucket: str) -> None:
		self._call("revoke_credentials", bucket)

	def _call(self, method: str, bucket: str) -> dict:
		response = requests.post(
			f"{self.instance.base_url}/api/method/{BUCKET_API}.{method}",
			json={"name": bucket, "region": self.region},
			headers={TOKEN_HEADER: self.token},
			timeout=TIMEOUT,
		)
		if response.status_code >= 400:
			frappe.throw(
				_("Cargo refused to {0} {1} ({2}): {3}").format(
					method.replace("_", " "), bucket, response.status_code, response.text[:200]
				)
			)

		return response.json().get("message") or {}
