from __future__ import annotations

from types import ModuleType

import frappe
import httpx
from atlas_wg_gateway_client import AuthenticatedClient
from atlas_wg_gateway_client.api.peers import list_peers, register_peer, remove_peer, replace_peers
from atlas_wg_gateway_client.models import PeerIdentity, PeerRegistration, PeerTable, RestoredPeer
from atlas_wg_gateway_client.types import Response
from frappe import _

GATEWAY_TIMEOUT = 30


class WireGuardGatewayError(frappe.ValidationError):
	"""The regional WireGuard gateway refused or missed a peer change."""


class WireGuardGatewayClient:
	"""Peer routes on one regional WireGuard gateway cluster."""

	def __init__(self, base_url: str, token: str):
		self.base_url = base_url
		self.token = token

	def register_peer(self, tenant_id: int, client_id: int, public_key: str) -> dict:
		"""Register one device and return its WireGuard settings."""
		body = PeerRegistration(tenant_id=tenant_id, client_id=client_id, public_key=public_key)
		response = self.send(register_peer, body, allow=(409, 503))
		# same key gets the same settings back so one retry is safe
		if response.status_code == 503:
			response = self.send(register_peer, body, allow=(409,))
		if response.status_code == 409:
			raise WireGuardGatewayError(_("This key is already used by another device. Generate a new one."))

		return response.parsed.to_dict()

	def remove_peer(self, tenant_id: int, client_id: int) -> None:
		"""Remove one device. The gateway succeeds when it is already gone."""
		self.send(remove_peer, PeerIdentity(tenant_id=tenant_id, client_id=client_id))

	def list_peers(self) -> list[dict]:
		"""Every device of every tenant in this region, with the node that serves it."""
		return [peer.to_dict() for peer in self.send(list_peers).parsed]

	def replace_peers(self, peers: list[dict]) -> None:
		"""Replace the complete device table of this region."""
		self.send(replace_peers, PeerTable(peers=[RestoredPeer.from_dict(peer) for peer in peers]))

	def send(
		self,
		endpoint: ModuleType,
		body: PeerRegistration | PeerIdentity | PeerTable | None = None,
		allow: tuple[int, ...] = (),
	) -> Response:
		kwargs = {"body": body} if body else {}
		try:
			with AuthenticatedClient(
				base_url=self.base_url, token=self.token, timeout=httpx.Timeout(GATEWAY_TIMEOUT, connect=5)
			) as client:
				response = endpoint.sync_detailed(client=client, **kwargs)
		except httpx.HTTPError:
			raise WireGuardGatewayError(
				_("The WireGuard gateway of this region is not answering. Try again in a few minutes.")
			)

		if response.status_code >= 300 and response.status_code not in allow:
			message = response.content.decode(errors="replace")[:500]
			raise WireGuardGatewayError(
				_("WireGuard gateway {0} returned HTTP {1}: {2}").format(
					self.base_url, int(response.status_code), message
				)
			)

		return response
