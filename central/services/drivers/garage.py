from __future__ import annotations

import frappe
import requests
from frappe import _

_TIMEOUT = 30


class GarageDriver:
	"""Talks to a Garage cluster's admin API (:3903). Garage mints the S3 access keys;
	Central names the bucket, scopes a key to it, and delivers both halves. Object
	traffic never passes through Central — a bench speaks S3 to the gateway (:3900)."""

	key = "storage"

	def create_bucket(self, backend, bucket: str) -> str:
		"""Create a bucket and return its id. Fails if the name is taken: Garage aliases
		are cluster-wide, and adopting a bucket Central did not create here would hand a
		key to whatever already sits under that name."""
		if self.get_bucket_id(backend, bucket):
			frappe.throw(_("The bucket name {0} is already taken. Pick another.").format(bucket))

		return self._call(backend, "CreateBucket", body={"globalAlias": bucket})["id"]

	def get_bucket_id(self, backend, bucket: str) -> str | None:
		info = self._call(backend, "GetBucketInfo", method="GET", params={"globalAlias": bucket}, throw=False)

		return info["id"] if info else None

	def mint_key(self, backend, name: str, bucket_id: str) -> dict:
		"""Create a key then allow key on that bucket."""
		key = self._call(backend, "CreateKey", body={"name": name})
		self._call(
			backend,
			"AllowBucketKey",
			body={
				"bucketId": bucket_id,
				"accessKeyId": key["accessKeyId"],
				"permissions": {"read": True, "write": True, "owner": False},
			},
		)

		return {"access_key_id": key["accessKeyId"], "secret_access_key": key["secretAccessKey"]}

	def revoke_key(self, backend, access_key_id: str) -> None:
		"""Revoke key access."""
		self._call(backend, "DeleteKey", params={"id": access_key_id})

	def _call(
		self,
		backend,
		endpoint: str,
		method: str = "POST",
		params: dict | None = None,
		body: dict | None = None,
		throw: bool = True,
	) -> dict | None:
		response = requests.request(
			method,
			f"{backend.base_url.rstrip('/')}/v2/{endpoint}",
			params=params,
			json=body,
			headers={"Authorization": f"Bearer {backend.get_password('control_api_secret')}"},
			timeout=_TIMEOUT,
		)
		if response.status_code >= 400:
			if not throw:
				return None
			frappe.throw(
				_("Garage request failed ({0}): {1}").format(response.status_code, response.text[:200])
			)

		return response.json()
