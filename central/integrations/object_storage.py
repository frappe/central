import frappe
import requests
from frappe import _

from central.central.doctype.region.region import Region
from central.sso import mint_cargo_token


class ObjectStorageConnectionError(frappe.ValidationError):
	"""Cargo could not confirm an object-storage operation."""


class ObjectStorageRejected(ObjectStorageConnectionError):
	"""Cargo explicitly rejected an object-storage operation."""


class ObjectStorageNotFound(ObjectStorageRejected):
	"""Cargo says the bucket does not exist."""


class ObjectStorageRequestUncertain(ObjectStorageConnectionError):
	"""Cargo may have completed a mutation without returning a usable receipt."""

	def __init__(self, *args):
		super().__init__(
			*(args or (_("Could not confirm the object storage operation. Do not retry automatically."),))
		)


class ObjectStorageClient:
	"""Call one region's Cargo bucket-control API."""

	def __init__(self, region: Region):
		self.cargo_endpoint = region.cargo_base_url
		self.region = region.name
		self.region_id = region.get_atlas_region_id()

	@classmethod
	def from_region(cls, region: str | Region) -> "ObjectStorageClient":
		region = frappe.get_doc("Region", region) if isinstance(region, str) else region
		if not frappe.db.exists(
			"Service Detail",
			{"service": "storage", "region": region.name, "status": "Available"},
			cache=False,
		):
			frappe.throw(
				_("No available storage service in region {0}.").format(region.name), frappe.ValidationError
			)

		return cls(region)

	def _call(self, method: str, name: str) -> dict:
		try:
			response = requests.post(
				f"{self.cargo_endpoint}/api/method/cargo.object_storage.api.bucket.{method}",
				json={"name": name, "region": self.region},
				headers={"X-Cargo-Access-Token": mint_cargo_token(self.region_id)},
				timeout=(5, 20),
				allow_redirects=False,
			)
		except requests.RequestException as error:
			raise ObjectStorageRequestUncertain() from error

		result = self._read_response(response)
		self._validate_receipt(method, name, result)
		return result

	def _validate_receipt(self, method: str, name: str, receipt: dict) -> None:
		valid = receipt.get("name") == name and receipt.get("region") == self.region
		if method in {"create_bucket", "rotate_credentials"}:
			credentials = receipt.get("credentials")
			valid = (
				valid
				and isinstance(credentials, dict)
				and all(
					isinstance(credentials.get(key), str) and credentials[key]
					for key in ("access_key", "secret_access_key")
				)
			)

		if not valid:
			raise ObjectStorageRequestUncertain()

	@staticmethod
	def _read_response(response: requests.Response) -> dict:
		if not 200 <= response.status_code < 300:
			frappe.logger().warning("Cargo object-storage request returned HTTP %s.", response.status_code)
			if response.status_code == 404:
				raise ObjectStorageNotFound(_("The bucket does not exist."))
			if 400 <= response.status_code < 500:
				raise ObjectStorageRejected(_("Object storage request was rejected."))
			raise ObjectStorageRequestUncertain()

		try:
			payload = response.json()
		except ValueError as error:
			raise ObjectStorageRequestUncertain() from error

		message = payload.get("message") if isinstance(payload, dict) else None
		if not isinstance(message, dict):
			raise ObjectStorageRequestUncertain()

		return message

	def create_bucket(self, name: str) -> dict:
		"""Create a bucket and return the credentials."""
		return self._call("create_bucket", name)

	def delete_bucket(self, name: str) -> dict:
		"""Delete a bucket."""
		return self._call("delete_bucket", name)

	def rotate_credentials(self, name: str) -> dict:
		"""Rotate credentials for a bucket."""
		return self._call("rotate_credentials", name)
