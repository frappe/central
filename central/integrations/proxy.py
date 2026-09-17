from __future__ import annotations

import frappe
import httpx
from atlas_proxy_client import AuthenticatedClient
from atlas_proxy_client.api.domains import delete_domain, patch_domain
from atlas_proxy_client.api.sites import delete_site, patch_site
from atlas_proxy_client.models import AddressUpdate
from atlas_proxy_client.types import Response
from frappe import _

PROXY_TIMEOUT = 30


class ProxyError(frappe.ValidationError):
	"""The regional proxy refused a route change."""


class ProxyClient:
	"""Site and custom-domain routes on one regional proxy cluster."""

	def __init__(self, base_url: str, token: str):
		self.base_url = base_url
		self.token = token

	def set_site(self, name: str, address: str) -> None:
		"""Route the site label `name` to an IPv6 address."""
		with self.get_client() as client:
			response = patch_site.sync_detailed(name, client=client, body=AddressUpdate(address=address))
		self.check(response)

	def delete_site(self, name: str) -> None:
		"""Remove the site route. The proxy succeeds when the route is already absent."""
		with self.get_client() as client:
			response = delete_site.sync_detailed(name, client=client)
		self.check(response)

	def set_domain(self, domain: str, address: str) -> None:
		"""Route the custom domain to an IPv6 address."""
		with self.get_client() as client:
			response = patch_domain.sync_detailed(domain, client=client, body=AddressUpdate(address=address))
		self.check(response)

	def delete_domain(self, domain: str) -> None:
		"""Remove the custom-domain route. The proxy succeeds when the route is already absent."""
		with self.get_client() as client:
			response = delete_domain.sync_detailed(domain, client=client)
		self.check(response)

	def get_client(self) -> AuthenticatedClient:
		return AuthenticatedClient(
			base_url=self.base_url, token=self.token, timeout=httpx.Timeout(PROXY_TIMEOUT)
		)

	def check(self, response: Response) -> None:
		if response.status_code >= 300:
			message = response.content.decode(errors="replace")[:500]
			raise ProxyError(
				_("Proxy {0} returned HTTP {1}: {2}").format(
					self.base_url, int(response.status_code), message
				)
			)
