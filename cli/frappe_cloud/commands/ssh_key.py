import argparse
from pathlib import Path

from frappe_cloud.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud.context import Context
from frappe_cloud.errors import CentralError

SSH_KEYS = "central.api.ssh_keys"
DEFAULT_KEY_FILES = ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub")


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "ssh-key", "Manage the team's SSH keys.")

	add_command(commands, "list", list_keys, "List the team's SSH keys.")

	parser = add_command(commands, "add", add_key, "Add a public key to the team.")
	parser.add_argument("--title", required=True, help="A title, such as the device name.")
	parser.add_argument("--file", type=Path, help="Public key file. Defaults to your key in ~/.ssh.")

	parser = add_command(commands, "delete", delete_key, "Remove a key from the team.")
	parser.add_argument("name", help="Key name, from `fcloud ssh-key list`.")
	add_yes_option(parser)


def list_keys(context: Context, args: argparse.Namespace) -> None:
	keys = context.client.get(f"{SSH_KEYS}.list_team_ssh_keys", team=context.client.require_team())
	columns = [
		("Name", "name"),
		("Title", "title"),
		("Fingerprint", "fingerprint"),
		("Servers", "server_count"),
		("Sync error", "last_sync_error"),
	]
	context.output.table(keys, columns, empty="This team has no SSH keys.")


def add_key(context: Context, args: argparse.Namespace) -> None:
	path = args.file or find_default_key()
	key = context.client.post(
		f"{SSH_KEYS}.create_team_ssh_key",
		team=context.client.require_team(),
		title=args.title,
		public_key=path.read_text().strip(),
	)
	context.output.result(key, f"Added {path} as {key['name']} ({key['fingerprint']}).")


def find_default_key() -> Path:
	for name in DEFAULT_KEY_FILES:
		path = Path.home() / ".ssh" / name
		if path.exists():
			return path
	raise CentralError("No public key in ~/.ssh. Pass one with --file.")


def delete_key(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Remove SSH key {args.name} from the team and its servers?", args.yes)
	context.client.post(f"{SSH_KEYS}.delete_team_ssh_key", team=context.client.require_team(), name=args.name)
	context.output.result({"name": args.name}, f"Removed SSH key {args.name}.")
