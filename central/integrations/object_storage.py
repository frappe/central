from __future__ import annotations

import json
from typing import TYPE_CHECKING

import boto3
import frappe
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from frappe import _

from central.sso import mint_cargo_token

if TYPE_CHECKING:
	from central.infrastructure.doctype.region.region import Region
	from central.services.doctype.team_service.team_service import TeamService


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
		self.cargo_endpoint = region.get_cargo_url()
		self.region = region.name
		self.region_id = region.get_atlas_region_id()

	@classmethod
	def from_region(cls, region: str | Region) -> ObjectStorageClient:
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

	def _call(self, method: str, name: str, **arguments) -> dict:
		try:
			response = requests.post(
				f"{self.cargo_endpoint}/api/method/cargo.object_storage.api.bucket.{method}",
				json={"name": name, "region": self.region, **arguments},
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
		elif method == "get_usage":
			valid = valid and isinstance(receipt.get("usage"), dict)

		if not valid:
			raise ObjectStorageRequestUncertain()

	@staticmethod
	def _read_response(response: requests.Response) -> dict:
		if not 200 <= response.status_code < 300:
			frappe.logger().warning("Cargo object-storage request returned HTTP %s.", response.status_code)
			if response.status_code == 404:
				raise ObjectStorageNotFound(_("The bucket does not exist."))
			if 400 <= response.status_code < 500:
				raise ObjectStorageRejected(
					ObjectStorageClient._read_validation_message(response)
					or _("Object storage request was rejected.")
				)
			raise ObjectStorageRequestUncertain()

		try:
			payload = response.json()
		except ValueError as error:
			raise ObjectStorageRequestUncertain() from error

		message = payload.get("message") if isinstance(payload, dict) else None
		if not isinstance(message, dict):
			raise ObjectStorageRequestUncertain()

		return message

	@staticmethod
	def _read_validation_message(response: requests.Response) -> str | None:
		"""The message Cargo threw for a request it found invalid, such as a taken or badly
		formed bucket name. Other refusals stay generic: they describe Cargo, not the request."""
		if response.status_code != 417:
			return None

		try:
			messages = json.loads(response.json()["_server_messages"])
			message = json.loads(messages[-1])["message"]
		except (ValueError, KeyError, IndexError, TypeError):
			return None

		return frappe.utils.strip_html(message) if isinstance(message, str) else None

	def create_bucket(self, name: str) -> dict:
		"""Create a bucket and return the credentials."""
		return self._call("create_bucket", name)

	def delete_bucket(self, name: str) -> dict:
		"""Delete a bucket."""
		return self._call("delete_bucket", name)

	def rotate_credentials(self, name: str, access_key: str) -> dict:
		"""Replace one of a bucket's keys and return the new one. Cargo makes the new key
		before it deletes `access_key`, so a failed rotation keeps the old key working."""
		return self._call("rotate_credentials", name, access_key=access_key)

	def get_usage(self, name: str) -> dict:
		"""What a bucket holds, against its caps."""
		return self._call("get_usage", name)

	def set_quota(self, name: str, size_gib: int, max_objects: int) -> dict:
		"""Cap a bucket's total size and object count. Zero lifts a cap."""
		return self._call("set_quota", name, size_gib=size_gib, max_objects=max_objects)


class BucketInteractions:
	"""Read one team bucket over S3 with the bucket's own key. Cargo controls buckets;
	objects are read from the region's S3 gateway directly."""

	MAXIMUM_PAGE_SIZE = 1000
	DOWNLOAD_URL_EXPIRY_SECONDS = 300

	def __init__(self, service: TeamService):
		self.bucket_name = service.bucket_name
		self.client = boto3.client(
			"s3",
			endpoint_url=service.endpoint_url,
			aws_access_key_id=service.access_key,
			aws_secret_access_key=service.get_password("secret_access_key"),
			region_name=service.region,
			config=Config(
				signature_version="s3v4",
				s3={"addressing_style": "path"},
				connect_timeout=5,
				read_timeout=20,
				retries={"max_attempts": 2},
			),
		)

	def fetch_objects(self, prefix: str = "", offset: str | None = None, limit: int = 100) -> dict:
		"""Paginate though the buckets' objects and folders."""
		arguments = {
			"Bucket": self.bucket_name,
			"Prefix": prefix,
			"Delimiter": "/",
			"MaxKeys": max(1, min(int(limit), self.MAXIMUM_PAGE_SIZE)),
		}
		if offset:
			arguments["ContinuationToken"] = offset

		page = self._request(self.client.list_objects_v2, **arguments)
		return {
			"objects": [
				{
					"key": item["Key"],
					"size_bytes": item["Size"],
					"last_modified": item["LastModified"].isoformat(),
					"etag": item["ETag"].strip('"'),
				}
				for item in page.get("Contents", [])
			],
			"folders": [folder["Prefix"] for folder in page.get("CommonPrefixes", [])],
			"next_offset": page.get("NextContinuationToken"),
		}

	def get_object_url(self, key: str) -> str:
		"""A short-lived download link for one object, so Central never streams its bytes."""
		# A presigned URL is signed locally, so ask S3 first: a link to nothing is a dead end.
		self._request(self.client.head_object, Bucket=self.bucket_name, Key=key)
		return self.client.generate_presigned_url(
			"get_object",
			Params={"Bucket": self.bucket_name, "Key": key},
			ExpiresIn=self.DOWNLOAD_URL_EXPIRY_SECONDS,
		)

	@staticmethod
	def _request(call, **arguments) -> dict:
		try:
			return call(**arguments)
		except ClientError as error:
			code = error.response.get("Error", {}).get("Code")
			if code in {"NoSuchBucket", "NoSuchKey", "404"}:
				raise ObjectStorageNotFound(_("The bucket or object does not exist.")) from error
			raise ObjectStorageRejected(_("Object storage refused the request.")) from error
		except BotoCoreError as error:
			raise ObjectStorageConnectionError(_("Object storage could not be reached.")) from error
