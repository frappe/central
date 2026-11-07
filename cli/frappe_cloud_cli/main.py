import argparse
import sys

from frappe_cloud_cli import __version__
from frappe_cloud_cli.commands import ai, auth, bucket, catalog, server, snapshot, ssh_key, team, wireguard
from frappe_cloud_cli.context import Context
from frappe_cloud_cli.errors import CentralError

COMMAND_MODULES = (auth, team, server, catalog, snapshot, ssh_key, wireguard, bucket, ai)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog="fcloud",
		description="Manage Frappe Cloud servers, networks and services from the terminal.",
		epilog="Add --json to any command for output that scripts and agents can read.",
	)
	parser.add_argument("--version", action="version", version=f"fcloud {__version__}")

	groups = parser.add_subparsers(dest="group", required=True, metavar="<command>")
	for module in COMMAND_MODULES:
		module.register(groups)

	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		args.handler(Context.create(args), args)
	except CentralError as error:
		print(f"Error: {error}", file=sys.stderr)
		return 1
	except OSError as error:
		print(f"Error: {error}", file=sys.stderr)
		return 1
	except KeyboardInterrupt:
		return 130

	return 0
