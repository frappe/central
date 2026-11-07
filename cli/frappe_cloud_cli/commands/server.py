import argparse
import os
import shutil
import sys
import time
import uuid
import webbrowser
from pathlib import Path

from frappe_cloud_cli.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud_cli.context import Context
from frappe_cloud_cli.errors import CentralError

SERVERS = "central.api.servers"
FINISHED_STATES = ("Succeeded", "Failed", "Timed Out")
POLL_SECONDS = 3

LIST_COLUMNS = [
	("ID", "resource_id"),
	("Title", "title"),
	("Region", "region"),
	("Status", lambda server: server.get("pending_action") or server["status"]),
	("Plan", lambda server: server.get("plan_title") or server.get("plan")),
	("Public IP", lambda server: server.get("public_ipv4") or server.get("public_ipv6")),
]


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "server", "Create, run and reach servers.")

	add_command(commands, "list", list_servers, "List the team's servers.")
	add_server_argument(add_command(commands, "show", show_server, "Show one server."))
	register_create(commands)

	for action in ("start", "stop", "restart"):
		parser = add_command(commands, action, run_power_action, f"{action.capitalize()} a server.")
		add_server_argument(parser)
		add_wait_option(parser)

	parser = add_command(commands, "terminate", terminate_server, "Delete a server and its disk.")
	add_server_argument(parser)
	parser.add_argument("--snapshot", action="store_true", help="Take a final snapshot first.")
	add_yes_option(parser)
	add_wait_option(parser)

	parser = add_command(commands, "rename", rename_server, "Change a server's title.")
	add_server_argument(parser)
	parser.add_argument("title", help="The new title.")

	register_access(commands)

	parser = add_command(commands, "wait", wait_command, "Wait for a server action to finish.")
	parser.add_argument("action", help="Action name, as printed when the action started.")
	parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait. Defaults to 900.")


def register_create(commands: argparse._SubParsersAction) -> None:
	parser = add_command(commands, "create", create_server, "Create a server.")
	parser.add_argument("title", help="A title for the server.")
	parser.add_argument("--region", required=True, help="Region, from `fcloud region list`.")
	parser.add_argument("--plan", required=True, help="Plan, from `fcloud plan list`.")
	parser.add_argument("--offering", help="Image offering, from `fcloud offering list`.")
	parser.add_argument("--image", help="Image ID. Defaults to the newest image of the offering.")
	parser.add_argument("--snapshot", help="Restore from this snapshot instead of an image.")
	parser.add_argument("--hostname", help="Hostname for the server.")
	parser.add_argument("--ssh-key", action="append", default=[], help="Team SSH key name. Repeat for more.")
	parser.add_argument("--public-ipv4", action="store_true", help="Attach a public IPv4 address.")
	parser.add_argument("--public-ipv6", action="store_true", help="Attach a public IPv6 address.")
	parser.add_argument("--firewall", action="store_true", help="Turn on the firewall.")
	parser.add_argument("--user-data", type=Path, help="A cloud-init file to run on first boot.")
	add_wait_option(parser)


def register_access(commands: argparse._SubParsersAction) -> None:
	parser = add_command(commands, "console", open_console, "Open the server's web console.")
	add_server_argument(parser)
	parser.add_argument("--tty", action="store_true", help="Open the serial console instead of a shell.")
	parser.add_argument("--print", action="store_true", help="Print the single-use URL; do not open it.")

	parser = add_command(commands, "ssh", ssh_server, "Connect to the server with SSH.")
	add_server_argument(parser)
	parser.add_argument("--user", default="root", help="User to sign in as. Defaults to root.")
	parser.add_argument(
		"ssh_args", nargs="*", metavar="-- ssh-argument", help="Arguments for ssh, after `--`."
	)


def add_server_argument(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("server", help="Server ID or title.")


def add_wait_option(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--wait", action="store_true", help="Wait until the action finishes.")
	parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait. Defaults to 900.")


def list_servers(context: Context, args: argparse.Namespace) -> None:
	registry = context.client.get(f"{SERVERS}.registry", team=context.client.require_team())
	context.output.table(registry["servers"], LIST_COLUMNS, empty="This team has no servers.")


def find_server(context: Context, identifier: str) -> dict:
	"""The team's server with this resource ID, else the only one with this title."""
	servers = context.client.get(f"{SERVERS}.registry", team=context.client.require_team())["servers"]
	for server in servers:
		if server["resource_id"] == identifier:
			return server

	matches = [server for server in servers if server["title"] == identifier]
	if len(matches) == 1:
		return matches[0]
	if matches:
		raise CentralError(f"{len(matches)} servers have the title '{identifier}'. Use the server ID.")
	raise CentralError(f"No server '{identifier}' in team {context.client.team}. Run `fcloud server list`.")


def get_overview(context: Context, identifier: str) -> dict:
	resource_id = find_server(context, identifier)["resource_id"]
	overview = context.client.get(
		f"{SERVERS}.server_overview", team=context.client.team, resource_id=resource_id
	)
	return overview["server"]


def show_server(context: Context, args: argparse.Namespace) -> None:
	server = get_overview(context, args.server)
	fields = [
		("ID", "resource_id"),
		("Title", "title"),
		("Status", "status"),
		("Region", "region"),
		("Plan", lambda server: server.get("plan_title") or server.get("plan")),
		("vCPUs", "vcpus"),
		("Memory MiB", "memory_megabytes"),
		("Disk GiB", "disk_gigabytes"),
		("Public IPv4", "public_ipv4"),
		("Public IPv6", "public_ipv6"),
		("Private IPv6", "ipv6_address"),
		("WireGuard", "has_wireguard_access"),
		("Firewall", "is_firewall_enabled"),
		("Protected", "is_termination_protected"),
		("SSH", "ssh_command"),
		("Created", "creation"),
	]
	context.output.record(server, fields)


def create_server(context: Context, args: argparse.Namespace) -> None:
	team = context.client.require_team()
	params = {
		"team": team,
		"region": args.region,
		"title": args.title,
		"plan": args.plan,
		"request_key": str(uuid.uuid4()),
		"hostname": args.hostname,
		"ssh_key_ids": args.ssh_key or None,
		"has_public_ipv4": args.public_ipv4,
		"has_public_ipv6": args.public_ipv6,
		"is_firewall_enabled": args.firewall,
		"user_data": args.user_data.read_text() if args.user_data else None,
		**get_image_params(context, args),
	}
	action = context.client.post(f"{SERVERS}.create_server", **params)
	report_action(context, args, action, f"Creating {args.title}")


def get_image_params(context: Context, args: argparse.Namespace) -> dict:
	if args.snapshot:
		return {"snapshot": args.snapshot}
	if not args.offering:
		raise CentralError("Pass --offering or --snapshot. Run `fcloud offering list` to see the offerings.")
	if args.image:
		return {"offering": args.offering, "image_id": args.image}

	return {"offering": args.offering, "image_id": get_newest_image_id(context, args.region, args.offering)}


def get_newest_image_id(context: Context, region: str, offering: str) -> str:
	images = []
	offset = 0
	while offset is not None:
		page = context.client.get(
			"central.api.images.list_images",
			team=context.client.team,
			region=region,
			offering=offering,
			offset=offset,
		)
		images += page["items"]
		offset = page.get("next_offset")

	if not images:
		raise CentralError(f"Offering {offering} has no available image in {region}.")
	return max(images, key=lambda image: image["created_at"])["id"]


def run_power_action(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	params = {"team": context.client.team, "resource_id": server["resource_id"]}
	action = context.client.post(f"{SERVERS}.{args.command}_server", **params)
	report_action(context, args, action, f"{args.command.capitalize()} {server['title']}")


def terminate_server(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	confirm(f"Terminate {server['title']} ({server['resource_id']})? Its disk is deleted.", args.yes)

	params = {
		"team": context.client.team,
		"resource_id": server["resource_id"],
		"take_snapshot": args.snapshot,
	}
	action = context.client.post(f"{SERVERS}.terminate_server", **params)
	report_action(context, args, action, f"Terminating {server['title']}")


def rename_server(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	params = {"team": context.client.team, "resource_id": server["resource_id"], "title": args.title}
	result = context.client.post(f"{SERVERS}.rename_server", **params)
	context.output.result(result, f"Renamed {server['resource_id']} to {args.title}.")


def report_action(context: Context, args: argparse.Namespace, action: dict, text: str) -> None:
	if args.wait:
		action = wait_for_action(context, action["action"], args.timeout)
	context.output.result(action, f"{text}: action {action['action']} is {action['status']}.")


def wait_command(context: Context, args: argparse.Namespace) -> None:
	action = wait_for_action(context, args.action, args.timeout)
	context.output.result(action, f"Action {action['action']} is {action['status']}.")


def wait_for_action(context: Context, name: str, timeout: int) -> dict:
	"""Poll the action until it finishes. A failed action raises its error."""
	deadline = time.monotonic() + timeout
	status = None
	while True:
		action = context.client.get(f"{SERVERS}.action_status", name=name)
		if action["status"] != status:
			status = action["status"]
			print(f"{name}: {status}", file=sys.stderr)
		if status in FINISHED_STATES:
			break
		if time.monotonic() >= deadline:
			raise CentralError(f"Action {name} is still {status}. Run `fcloud server wait {name}`.")
		time.sleep(POLL_SECONDS)

	if status != "Succeeded":
		error = action.get("error") or {}
		raise CentralError(f"Action {name} is {status}. {error.get('message') or ''}".strip())
	return action


def open_console(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	params = {
		"team": context.client.team,
		"resource_id": server["resource_id"],
		"mode": "tty" if args.tty else "ssh",
	}
	url = context.client.post(f"{SERVERS}.open_console", **params)["url"]
	if args.print or context.output.is_json or not webbrowser.open(url):
		context.output.result({"url": url}, f"Open this URL within 30 seconds. It works once:\n{url}")
		return

	context.output.line(f"Opened the console for {server['title']} in your browser.")


def ssh_server(context: Context, args: argparse.Namespace) -> None:
	server = get_overview(context, args.server)
	address = get_ssh_address(server)
	if not shutil.which("ssh"):
		raise CentralError("Install an OpenSSH client to use `fcloud server ssh`.")

	# ssh would read a destination that starts with a dash as an option.
	if args.user.startswith("-"):
		raise CentralError("A user name cannot start with '-'.")
	os.execvp("ssh", ["ssh", f"{args.user}@{address}", *args.ssh_args])


def get_ssh_address(server: dict) -> str:
	"""A public address, else the private one, which only a WireGuard device can reach."""
	address = server.get("public_ipv6") or server.get("public_ipv4")
	if address:
		return address
	if server.get("has_wireguard_access") and server.get("ipv6_address"):
		return server["ipv6_address"]

	raise CentralError(
		f"{server['title']} has no public address. Attach one in the console, or connect over WireGuard "
		f"with `fcloud wireguard allow {server['resource_id']}`."
	)
