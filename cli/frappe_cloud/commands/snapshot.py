import argparse

from frappe_cloud.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud.commands.server import find_server
from frappe_cloud.context import Context
from frappe_cloud.errors import CentralError

SNAPSHOTS = "central.api.snapshots"


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "snapshot", "Take and remove server snapshots.")

	parser = add_command(commands, "list", list_snapshots, "List the team's snapshots.")
	parser.add_argument("--server", help="Only this server's snapshots. Server ID or title.")

	parser = add_command(commands, "create", create_snapshot, "Take a snapshot of a server now.")
	parser.add_argument("server", help="Server ID or title.")
	parser.add_argument("--title", help="A title for the snapshot.")

	parser = add_command(commands, "delete", delete_snapshots, "Delete snapshots.")
	parser.add_argument("names", nargs="+", help="Snapshot names, from `fcloud snapshot list`.")
	add_yes_option(parser)


def list_snapshots(context: Context, args: argparse.Namespace) -> None:
	resource_id = find_server(context, args.server)["resource_id"] if args.server else None
	result = context.client.get(
		f"{SNAPSHOTS}.list_snapshots", team=context.client.require_team(), resource_id=resource_id
	)
	columns = [
		("Name", "name"),
		("Title", "title"),
		("Server", "server_title"),
		("Region", "region"),
		("Type", "snapshot_type"),
		("Status", "status"),
		("Size GiB", "size_gib"),
		("Created", "creation"),
	]
	context.output.table(result["snapshots"], columns, empty="No snapshots.")


def create_snapshot(context: Context, args: argparse.Namespace) -> None:
	server = find_server(context, args.server)
	snapshot = context.client.post(
		f"{SNAPSHOTS}.take_snapshot",
		team=context.client.team,
		resource_id=server["resource_id"],
		title=args.title,
	)
	context.output.result(snapshot, f"Taking a snapshot of {server['title']}.")


def delete_snapshots(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Delete {len(args.names)} snapshot(s)? They cannot be restored.", args.yes)
	result = context.client.post(
		f"{SNAPSHOTS}.delete_snapshots", team=context.client.require_team(), names=args.names
	)
	if result["deleted"]:
		context.output.result(result, f"Deleting {', '.join(result['deleted'])}.")
	if result["failed"]:
		reasons = "; ".join(f"{name}: {reason}" for name, reason in result["failed"].items())
		raise CentralError(f"Could not delete {len(result['failed'])} snapshot(s). {reasons}")
