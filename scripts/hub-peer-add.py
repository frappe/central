#!/usr/bin/env python3
# Add (or update) one Atlas peer on the hub's wg0 and persist it:
#   wg set wg0 peer <pubkey> allowed-ips <tunnel_ip>/32 endpoint <atlas_ip:port> \
#          persistent-keepalive 25
#   wg-quick save wg0
# The hub dials the spoke, so the endpoint (the Atlas's public ip:port) is required;
# keepalive holds the session open through the spoke's firewall. Idempotent — re-
# adding the same pubkey updates it in place. Runs on the CENTRAL host via
# central.host_task.run_host_task; wg / wg-quick are sudoers-pinned.

import os
import sys
import typing
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import central.wireguard as wireguard
from central._task import TaskInputs, TaskResult


@dataclass(frozen=True)
class HubPeerAddInputs(TaskInputs):
	"""Add an Atlas peer to the hub interface."""

	command: typing.ClassVar[str] = "hub-peer-add"
	peer_public_key: str  # the Atlas's WireGuard public key
	allowed_ips: str  # the Atlas's tunnel address with mask, e.g. 10.88.0.2/32
	endpoint: str  # the Atlas's public wg endpoint, ip:port (the hub dials this)
	keepalive: int = 25
	interface: str = "wg0"


@dataclass(frozen=True)
class HubPeerAddResult(TaskResult):
	peer_public_key: str
	allowed_ips: str
	endpoint: str
	interface: str


def main() -> None:
	inputs = HubPeerAddInputs.from_args()

	wireguard.add_peer(
		inputs.interface,
		inputs.peer_public_key,
		inputs.allowed_ips,
		inputs.endpoint,
		inputs.keepalive,
	)

	HubPeerAddResult(
		peer_public_key=inputs.peer_public_key,
		allowed_ips=inputs.allowed_ips,
		endpoint=inputs.endpoint,
		interface=inputs.interface,
	).emit()
	print(f"Peer {inputs.peer_public_key[:16]}… → {inputs.allowed_ips} via {inputs.endpoint}.")


if __name__ == "__main__":
	main()
