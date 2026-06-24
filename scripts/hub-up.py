#!/usr/bin/env python3
# Bring up Central's WireGuard hub interface idempotently: generate the hub keypair
# locally if absent (the private key never leaves the host, 0600), write wg0.conf
# from it, `wg-quick up wg0`, and enable wg-quick@wg0 for reboot persistence. Emit
# the hub's PUBLIC key + address + listen port as the typed ATLAS_RESULT= line the
# Central Tunnel Settings controller parses and stores.
#
# Runs on the CENTRAL controller host (it IS the hub), invoked through the local
# host-task runner (central.host_task.run_host_task) — the sibling of Atlas's
# issue-cert.py controller task. Privileged commands (wg, wg-quick, systemctl) are
# sudoers-pinned (scripts/sudoers.d/central-tunnel). Idempotent: safe to re-run.

import os
import sys
import typing
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import central.wireguard as wireguard
from central._task import TaskInputs, TaskResult


@dataclass(frozen=True)
class HubUpInputs(TaskInputs):
	"""Initialize the WireGuard hub interface on the Central host."""

	command: typing.ClassVar[str] = "hub-up"
	private_key_path: str  # 0600 path to the hub private key (generated here if absent)
	address: str = "10.88.0.1/16"  # the hub's address on wg0
	listen_port: int = 51820  # the hub's wg UDP listen port
	interface: str = "wg0"


@dataclass(frozen=True)
class HubUpResult(TaskResult):
	public_key: str
	address: str
	listen_port: int
	interface: str


def main() -> None:
	inputs = HubUpInputs.from_args()

	public_key = wireguard.ensure_keypair(inputs.private_key_path)
	wireguard.ensure_interface(inputs.interface, inputs.private_key_path, inputs.address, inputs.listen_port)

	HubUpResult(
		public_key=public_key,
		address=inputs.address,
		listen_port=inputs.listen_port,
		interface=inputs.interface,
	).emit()
	print(f"Hub {inputs.interface} up at {inputs.address}, listening on :{inputs.listen_port}.")


if __name__ == "__main__":
	main()
