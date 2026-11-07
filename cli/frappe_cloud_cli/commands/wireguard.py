import argparse
import base64
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from frappe_cloud_cli.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud_cli.commands.server import find_server
from frappe_cloud_cli.context import Context
from frappe_cloud_cli.errors import CentralError

WIREGUARD = "central.api.wireguard"
# wg-quick takes the interface name from the file name, at most 15 characters.
INTERFACE_NAME_LENGTH = 15


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "wireguard", "Reach servers on their private network over WireGuard.")

	add_command(commands, "list", list_devices, "List the team's WireGuard devices and servers.")

	parser = add_command(commands, "create", create_device, "Add this device and write its WireGuard config.")
	parser.add_argument("--region", required=True, help="Region whose gateway the device connects to.")
	parser.add_argument("--title", required=True, help="A title for the device, such as your laptop's name.")
	parser.add_argument(
		"--output", help="Config file to write, or - for standard output. Defaults to <title>.conf."
	)

	parser = add_command(commands, "delete", delete_device, "Remove a device from its gateway.")
	parser.add_argument("name", help="Device name, from `fcloud wireguard list`.")
	add_yes_option(parser)

	for name, summary in (
		("allow", "Let WireGuard devices reach a server."),
		("deny", "Stop WireGuard access to a server."),
	):
		parser = add_command(commands, name, set_server_access, summary)
		parser.add_argument("server", help="Server ID or title.")


def list_devices(context: Context, args: argparse.Namespace) -> None:
	result = context.client.get(f"{WIREGUARD}.list_wireguard_devices", team=context.client.require_team())
	if context.output.is_json:
		return context.output.json(result)

	device_columns = [
		("Name", "name"),
		("Title", "title"),
		("Region", "region"),
		("Status", "status"),
		("Address", "address"),
		("Added by", "added_by_name"),
	]
	context.output.table(result["devices"], device_columns, empty="This team has no WireGuard devices.")
	context.output.line()
	server_columns = [
		("Server", "resource_id"),
		("Title", "title"),
		("Region", "region"),
		("Private IPv6", "ipv6_address"),
		("Access", "has_wireguard_access"),
		("Firewall blocks", "is_blocked_by_firewall"),
	]
	context.output.table(result["servers"], server_columns, empty="No server is in a region with a gateway.")


def create_device(context: Context, args: argparse.Namespace) -> None:
	if args.output == "-":
		return context.output.line(register_device(context, args)[1])

	# Claim the file first: a device whose private key is lost must be added again.
	path = Path(args.output or f"{get_interface_name(args.title)}.conf")
	with open_private_file(path) as file:
		device, config = register_device(context, args)
		file.write(config)

	context.output.result(
		{**device, "config_path": str(path)},
		f"Added {device['title']} at {device['address']}. Wrote {path}.\n"
		f"Connect with: sudo wg-quick up {path.resolve()}",
	)


def register_device(context: Context, args: argparse.Namespace) -> tuple[dict, str]:
	"""Register a new key pair with the region's gateway. Returns the device and its config."""
	private_key, public_key = generate_key_pair()
	device = context.client.post(
		f"{WIREGUARD}.create_wireguard_device",
		team=context.client.require_team(),
		region=args.region,
		title=args.title,
		public_key=public_key,
	)
	return device, build_config(device, private_key)


def generate_key_pair() -> tuple[str, str]:
	"""A WireGuard key pair, made here. Central receives only the public key."""
	private_key = X25519PrivateKey.generate()
	private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
	public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
	return base64.b64encode(private_bytes).decode(), base64.b64encode(public_bytes).decode()


def build_config(device: dict, private_key: str) -> str:
	"""The same wg-quick config the console downloads."""
	allowed_ips = ", ".join(device["allowed_ips"].split("\n"))
	return "\n".join(
		[
			"[Interface]",
			f"PrivateKey = {private_key}",
			f"Address = {device['address']}",
			"",
			"[Peer]",
			f"PublicKey = {device['gateway_public_key']}",
			f"AllowedIPs = {allowed_ips}",
			f"Endpoint = {device['endpoint']}",
			"PersistentKeepalive = 25",
			"",
		]
	)


def get_interface_name(title: str) -> str:
	name = re.sub(r"[^a-z0-9]+", "-", title.lower())[:INTERFACE_NAME_LENGTH].strip("-")
	return name or "wireguard"


@contextmanager
def open_private_file(path: Path) -> Iterator[TextIO]:
	"""A new file that only its owner can read, because it holds a private key. It is removed on failure."""
	try:
		descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
	except FileExistsError:
		raise CentralError(f"{path} already exists. Pass another path with --output.")
	except OSError as error:
		raise CentralError(f"Could not create {path}: {error.strerror}.")

	try:
		with os.fdopen(descriptor, "w") as file:
			yield file
	except BaseException:
		path.unlink(missing_ok=True)
		raise


def delete_device(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Remove WireGuard device {args.name}? It can no longer connect.", args.yes)
	result = context.client.post(
		f"{WIREGUARD}.delete_wireguard_device", team=context.client.require_team(), name=args.name
	)
	text = (
		f"Removed {args.name}."
		if result["is_removed"]
		else f"Removing {args.name}. The gateway is not reachable yet."
	)
	context.output.result(result, text)


def set_server_access(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	is_enabled = args.command == "allow"
	context.client.post(
		"central.api.servers.set_server_wireguard_access",
		team=context.client.team,
		resource_id=server["resource_id"],
		enabled=is_enabled,
	)
	state = "can" if is_enabled else "cannot"
	context.output.result(
		{"resource_id": server["resource_id"], "has_wireguard_access": is_enabled},
		f"WireGuard devices {state} reach {server['title']} now.",
	)
