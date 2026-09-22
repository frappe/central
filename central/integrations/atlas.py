from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import frappe
import requests
from frappe import _

from central.errors import AtlasConnectionError, AtlasRejected, AtlasRequestUncertain, AtlasResourceGone
from central.iam import can, user_has_operator_bypass
from central.identity.doctype.team.tenant import validate_tenant_id
from central.sso import central_url, mint_atlas_token

if TYPE_CHECKING:
	from central.infrastructure.doctype.region.region import Region


class AtlasClient:
	"""Use the regional tenant API with explicit identity and mutation outcomes."""

	def __init__(self, instance: Region, tenant_id: int):
		if type(tenant_id) is not int:
			frappe.throw(_("The tenant ID must be a whole number."), AtlasConnectionError)

		if tenant_id == 0:
			if not user_has_operator_bypass():
				frappe.throw(_("Only an operator can use the system tenant."), frappe.PermissionError)
		else:
			validate_tenant_id(tenant_id)

		self.instance = instance
		self.tenant_id = tenant_id

	@classmethod
	def for_operator(cls, instance: Region) -> AtlasClient:
		"""1. Require the operator bypass before using the system tenant."""
		if not user_has_operator_bypass():
			frappe.throw(_("Only an operator can check regional configuration."), frappe.PermissionError)

		return cls(instance, 0)

	@classmethod
	def for_team(cls, instance: Region, team: str, capability: str = "server:view") -> AtlasClient:
		"""Resolve the regional tenant.

		1. Require server view access.
		2. Read the tenant ID from the authorized Team.
		"""
		if not can(frappe.session.user, team, capability):
			frappe.throw(_("You cannot view servers for this Team."), frappe.PermissionError)

		tenant_id = frappe.db.get_value("Team", team, "tenant_id")
		validate_tenant_id(tenant_id)
		return cls(instance, tenant_id)

	def _get(self, path: str, params: dict | None = None) -> dict:
		return self._request("GET", path, params=params)

	def create_vm(self, payload: dict) -> dict:
		"""Submit once. A lost reply must never trigger an automatic create retry."""
		return self._request("POST", "virtual-machines", payload=payload)

	def get_vm(self, name: str) -> dict:
		return self._get(f"virtual-machines/{quote(name, safe='')}")

	def list_vms(self, limit: int = 100) -> list[dict]:
		"""One page of this tenant's servers, newest first."""
		page = self._get("virtual-machines", params={"offset": 0, "limit": limit})
		items = page.get("items")
		if not isinstance(items, list):
			frappe.throw(_("Atlas returned an invalid server page."), AtlasConnectionError)
		return items

	def vm_action(self, name: str, action: str) -> dict:
		path = f"virtual-machines/{quote(name, safe='')}"
		if action == "terminate":
			return self._request("DELETE", path)
		if action not in ("start", "stop", "restart"):
			frappe.throw(_("This server action is not supported."))

		return self._request("POST", f"{path}/actions/{action}")

	def resize(
		self,
		name: str,
		cpu_millicores: int,
		memory_mib: int,
		disk_mib: int,
		sleep_after_idle_seconds: int = 0,
	) -> dict:
		"""Set CPU, memory and disk in one call. Atlas takes a CPU or memory change only on a
		stopped VM, resizes it in place or moves it to a host that fits (reporting a `migrating`
		state meanwhile), and never shrinks the disk. Zero seconds turns idle shutdown off,
		since a resized server has outgrown the hobby sleep."""
		payload = {
			"cpu_millicores": cpu_millicores,
			"memory_mib": memory_mib,
			"disk_mib": disk_mib,
			"sleep_after_idle_seconds": sleep_after_idle_seconds,
		}
		return self._request(
			"POST", f"virtual-machines/{quote(name, safe='')}/actions/resize", payload=payload
		)

	def update_disk(self, name: str, disk_mib: int) -> dict:
		"""Grow the disk online, without stopping the VM. Atlas refuses a smaller size."""
		return self._request(
			"PATCH", f"virtual-machines/{quote(name, safe='')}/disk", payload={"disk_mib": disk_mib}
		)

	def check_connection(self) -> None:
		response = self._get("images", params={"limit": 1})
		if not isinstance(response.get("items"), list) or type(response.get("has_more")) is not bool:
			frappe.throw(_("Atlas returned an invalid image list."), AtlasConnectionError)

	def configure_webhooks(self, webhook_secret: str) -> None:
		"""Point this region's virtual-machine-state webhook deliveries at Central's
		receiver. Separate from `check_connection`: this mutates Atlas's configuration,
		it does not just read from it."""
		central_id = frappe.get_single_value("Central Settings", "central_id")
		payload = {
			"request_url": f"{central_url()}/api/method/central.api.state_delivery.receive",
			"webhook_secret": webhook_secret,
			"enabled": True,
			"central_id": central_id or 1,
		}
		self._request("PUT", "webhooks", payload=payload)

	def get_image(self, image_id: str) -> dict:
		if not image_id:
			frappe.throw(_("An Atlas image ID is required."), AtlasConnectionError)

		image = self._get(f"images/{quote(image_id, safe='')}")
		if image.get("id") != image_id:
			frappe.throw(_("Atlas returned a different image."), AtlasConnectionError)

		return image

	def list_system_images(self, tags: dict[str, str], offset: int = 0) -> dict:
		"""Return one regional page, preserving pagination after availability filtering."""
		if type(offset) is not int or offset < 0:
			frappe.throw(_("Image offset must be a nonnegative whole number."))

		params = {
			"image_type": "system",
			"tag": ",".join(f"{key}:{value}" for key, value in tags.items()),
			"offset": offset,
			"limit": 100,
		}
		page = self._get("images", params=params)
		self._validate_image_page(page, offset)
		images = [self.read_system_image(image, tags) for image in page["items"]]

		return {
			"items": [image for image in images if image["enabled"] and image["status"] == "available"],
			"next_offset": offset + page["limit"] if page["has_more"] else None,
		}

	def _validate_image_page(self, page: dict, offset: int) -> None:
		valid = (
			isinstance(page.get("items"), list)
			and type(page.get("has_more")) is bool
			and type(page.get("offset")) is int
			and page["offset"] == offset
			and type(page.get("limit")) is int
			and 1 <= page["limit"] <= 100
		)
		if not valid or len(page["items"]) > page["limit"] or (page["has_more"] and not page["items"]):
			frappe.throw(_("Atlas returned an invalid image page."), AtlasConnectionError)

	def read_system_image(self, image: dict, required_tags: dict[str, str]) -> dict:
		if not isinstance(image, dict):
			frappe.throw(_("Atlas returned invalid image metadata."), AtlasConnectionError)

		tags = image.get("tags")
		valid = (
			image.get("image_type") == "system"
			and isinstance(tags, dict)
			and all(isinstance(key, str) and isinstance(value, str) for key, value in tags.items())
			and all(tags.get(key) == value for key, value in required_tags.items())
		)
		if not valid:
			frappe.throw(_("Atlas returned an image outside the requested offering."), AtlasConnectionError)

		for field in ("id", "title", "architecture", "status"):
			if not isinstance(image.get(field), str) or not image[field]:
				frappe.throw(_("Atlas returned incomplete image metadata."), AtlasConnectionError)

		if (
			type(image.get("enabled")) is not bool
			or type(image.get("rootfs_size_mib")) is not int
			or image["rootfs_size_mib"] < 0
			or (image["status"] == "available" and image["rootfs_size_mib"] == 0)
			# Build time is what separates two builds of the same Frappe version.
			or type(image.get("created_at")) is not int
			or image["created_at"] <= 0
		):
			frappe.throw(
				_("Atlas returned invalid image availability, disk size, or build time."),
				AtlasConnectionError,
			)

		return {
			field: image.get(field)
			for field in (
				"id",
				"title",
				"architecture",
				"status",
				"enabled",
				"rootfs_size_mib",
				"created_at",
				"tags",
			)
		}

	def _request(
		self, method: str, path: str, params: dict | None = None, payload: dict | None = None
	) -> dict:
		base_url, region_id = self._configuration()
		try:
			token = mint_atlas_token(region_id)
		except frappe.ValidationError as error:
			frappe.throw(str(error), AtlasConnectionError)

		headers = {
			"Authorization": f"Bearer {token}",
			"X-Tenant-ID": str(self.tenant_id),
			"Accept": "application/json",
		}

		try:
			response = requests.request(
				method,
				f"{base_url}/api/atlas/{path}",
				headers=headers,
				params=params,
				json=payload,
				timeout=(5, 20),
				allow_redirects=False,
			)
		except requests.RequestException:
			if method != "GET":
				raise AtlasRequestUncertain(
					_("Atlas may have accepted the request. Do not repeat it until its result is confirmed.")
				)
			frappe.throw(
				_("Atlas could not be reached. Check the regional URL and network."), AtlasConnectionError
			)

		return self._read_response(response, method)

	def _configuration(self) -> tuple[str, int]:
		if self.instance.status == "Disabled":
			frappe.throw(_("This Atlas region is disabled."), AtlasConnectionError)

		region_id = self.instance.get_atlas_region_id()
		base_url = (self.instance.base_url or "").rstrip("/")
		self._validate_url(base_url)

		return base_url, region_id

	def _validate_url(self, base_url: str) -> None:
		try:
			parsed = urlsplit(base_url)
		except ValueError:
			frappe.throw(_("Enter a valid Atlas base URL."), AtlasConnectionError)

		if not parsed.hostname or any((parsed.username, parsed.password, parsed.query, parsed.fragment)):
			frappe.throw(
				_("Enter an Atlas base URL without credentials, a query, or a fragment."),
				AtlasConnectionError,
			)

		local_host = parsed.hostname in ("localhost", "127.0.0.1", "::1") or parsed.hostname.endswith(
			".localhost"
		)
		local_http = frappe.conf.developer_mode and local_host and parsed.scheme == "http"
		if parsed.scheme != "https" and not local_http:
			frappe.throw(_("Atlas requires HTTPS except for local development hosts."), AtlasConnectionError)

	def _read_response(self, response: requests.Response, method: str = "GET") -> dict:
		if response.status_code in (401, 403):
			frappe.throw(
				_("Atlas rejected Central authentication. Check the region ID and trusted key."),
				AtlasConnectionError,
			)

		if response.status_code == 404:
			raise AtlasResourceGone(_("The regional resource was not found."))

		if method != "GET" and response.status_code >= 500:
			raise AtlasRequestUncertain(_("Atlas could not confirm the operation result."))

		if response.status_code not in (200, 201, 202, 204):
			error_type = (
				AtlasRejected
				if method != "GET" and 400 <= response.status_code < 500
				else AtlasConnectionError
			)
			if method != "GET" and response.status_code < 400:
				error_type = AtlasRequestUncertain
			message = _("Atlas returned HTTP {0} for the regional request.").format(response.status_code)
			if response.status_code in (400, 409, 422):
				try:
					error = response.json().get("error", {})
				except ValueError, AttributeError:
					error = {}
				if isinstance(error, dict) and isinstance(error.get("message"), str):
					message = frappe.utils.escape_html(error["message"][:1000])
			raise error_type(message)

		if response.status_code == 204:
			return {}

		try:
			data = response.json()
		except requests.exceptions.JSONDecodeError:
			raise (AtlasRequestUncertain if method != "GET" else AtlasConnectionError)(
				_("Atlas returned an invalid JSON response.")
			)

		if not isinstance(data, dict):
			raise (AtlasRequestUncertain if method != "GET" else AtlasConnectionError)(
				_("Atlas returned an invalid response document.")
			)

		return data
