from __future__ import annotations

import typing
from typing import NoReturn

import frappe
import requests
from frappe import _

if typing.TYPE_CHECKING:
	from central.services.doctype.service_backend.service_backend import ServiceBackend

_TIMEOUT = 30


class GarageDriver:
	"""Talks to a Garage cluster's admin API (:3903). Garage mints the S3 access keys;
	Central names the bucket, scopes a key to it, and delivers both halves. Object
	traffic never passes through Central — a bench speaks S3 to the gateway (:3900)."""

	key = "storage"

	def create_bucket(self, backend: ServiceBackend) -> str:
		"""Create an unnamed bucket and return its id. The name goes on last, once the
		bucket is usable, so an abandoned one squats no name."""
		return self._call(backend, "CreateBucket", body={})["id"]

	def attach_alias(self, backend: ServiceBackend, bucket_id: str, alias: str) -> None:
		"""Name the bucket, once it is usable. Garage arbitrates the name: it is the only
		thing that can, since two callers can both pass an availability check and only one
		can win. Its rejection names the winning bucket's id, so it is answered rather than
		relayed."""
		response = self._request(
			backend, "AddBucketAlias", body={"bucketId": bucket_id, "globalAlias": alias}
		)
		if not response.ok:
			if "already exists" in response.text:
				frappe.throw(
					_("The bucket name {0} is already taken. Pick another.").format(alias),
					title=_("Bucket name taken"),
				)

			frappe.throw(
				_("Garage request failed ({0}): {1}").format(response.status_code, response.text[:200])
			)

	def get_bucket_id(self, backend: ServiceBackend, bucket: str) -> str | None:
		"""The bucket's id, or None when no such alias exists — a 404 is an answer here,
		not a failure."""
		response = self._request(backend, "GetBucketInfo", method="GET", params={"globalAlias": bucket})

		return response.json()["id"] if response.ok else None

	def mint_key(self, backend: ServiceBackend, name: str, bucket_id: str) -> dict:
		"""Create a key then allow it on that bucket. A key that cannot be granted is
		deleted rather than left live with no bucket and nothing tracking it."""
		key = self._call(backend, "CreateKey", body={"name": name})
		try:
			self._call(
				backend,
				"AllowBucketKey",
				body={
					"bucketId": bucket_id,
					"accessKeyId": key["accessKeyId"],
					"permissions": {"read": True, "write": True, "owner": False},
				},
			)
		except Exception:
			self.revoke_key(backend, key["accessKeyId"])
			raise

		return {"access_key_id": key["accessKeyId"], "secret_access_key": key["secretAccessKey"]}

	def provision_site(self, backend: ServiceBackend, site: str, options: dict) -> NoReturn:
		frappe.throw(_("Object storage is issued per bench, not per site."))

	def provision_key(self, backend: ServiceBackend, name: str, email: str, options: dict) -> NoReturn:
		frappe.throw(_("Object storage keys are issued per bench, not per team."))

	def delete_bucket(self, backend: ServiceBackend, bucket_id: str) -> None:
		"""Destroy a bucket. Garage refuses a non-empty one, which is the backstop that
		keeps this from ever taking objects with it. Keys allowed on it survive — revoke
		them separately."""
		self._call(backend, "DeleteBucket", params={"id": bucket_id})

	def revoke_key(self, backend: ServiceBackend, access_key_id: str) -> None:
		"""Revoke key access."""
		self._call(backend, "DeleteKey", params={"id": access_key_id})

	def _call(
		self,
		backend: ServiceBackend,
		endpoint: str,
		method: str = "POST",
		params: dict | None = None,
		body: dict | None = None,
	) -> dict:
		response = self._request(backend, endpoint, method=method, params=params, body=body)
		if not response.ok:
			frappe.throw(_(f"Garage request failed ({response.status_code}): {response.text[:200]}"))

		return response.json()

	def _request(
		self,
		backend: ServiceBackend,
		endpoint: str,
		method: str = "POST",
		params: dict | None = None,
		body: dict | None = None,
	) -> requests.Response:
		return requests.request(
			method,
			f"{backend.base_url.rstrip('/')}/v2/{endpoint}",
			params=params,
			json=body,
			headers={"Authorization": f"Bearer {backend.get_password('control_api_secret')}"},
			timeout=_TIMEOUT,
		)
