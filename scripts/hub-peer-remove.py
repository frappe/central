#!/usr/bin/env python3
# Remove one Atlas peer from the hub's wg0 and persist:
#   wg set wg0 peer <pubkey> remove   (best-effort — a missing peer is not an error)
#   wg-quick save wg0
# The rollback path for a half-added peer and the teardown for a de-registered Atlas.
# Runs on the CENTRAL host via central.host_task.run_host_task; sudoers-pinned.

import os
import sys
import typing
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import central.wireguard as wireguard
from central._task import TaskInputs, TaskResult


@dataclass(frozen=True)
class HubPeerRemoveInputs(TaskInputs):
	"""Remove an Atlas peer from the hub interface."""

	command: typing.ClassVar[str] = "hub-peer-remove"
	peer_public_key: str  # the Atlas's WireGuard public key
	interface: str = "wg0"


@dataclass(frozen=True)
class HubPeerRemoveResult(TaskResult):
	peer_public_key: str
	interface: str
	removed: bool


def main() -> None:
	inputs = HubPeerRemoveInputs.from_args()

	wireguard.remove_peer(inputs.interface, inputs.peer_public_key)

	HubPeerRemoveResult(
		peer_public_key=inputs.peer_public_key,
		interface=inputs.interface,
		removed=True,
	).emit()
	print(f"Peer {inputs.peer_public_key[:16]}… removed from {inputs.interface}.")


if __name__ == "__main__":
	main()
