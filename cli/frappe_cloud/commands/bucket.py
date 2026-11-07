import argparse

from frappe_cloud.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud.context import Context

STORAGE = "central.services.api.storage"
CREDENTIAL_FIELDS = [
	("Name", "name"),
	("Bucket", "bucket_name"),
	("Region", "region"),
	("Endpoint", "endpoint_url"),
	("Access key", "access_key"),
	("Secret key", "secret_access_key"),
]


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "bucket", "Manage S3-compatible object storage buckets.")

	add_command(commands, "list", list_buckets, "List the team's buckets.")
	add_command(commands, "regions", list_regions, "List the regions that offer object storage.")

	parser = add_command(commands, "create", create_bucket, "Create a bucket and print its secret once.")
	parser.add_argument("bucket_name", help="A name for the bucket.")
	parser.add_argument("--region", required=True, help="Region, from `fcloud bucket regions`.")

	parser = add_command(commands, "usage", show_usage, "Show a bucket's size, object count and quota.")
	parser.add_argument("name", help="Bucket name, from `fcloud bucket list`.")

	parser = add_command(
		commands, "rotate", rotate_credentials, "Replace a bucket's key and print the new secret."
	)
	parser.add_argument("name", help="Bucket name, from `fcloud bucket list`.")
	add_yes_option(parser)

	parser = add_command(commands, "delete", delete_bucket, "Delete an empty bucket.")
	parser.add_argument("name", help="Bucket name, from `fcloud bucket list`.")
	add_yes_option(parser)


def list_buckets(context: Context, args: argparse.Namespace) -> None:
	storage = context.client.get(f"{STORAGE}.get_object_storage", team=context.client.require_team())
	columns = [
		("Name", "name"),
		("Bucket", "bucket_name"),
		("Region", "region"),
		("Status", "status"),
		("Endpoint", "endpoint_url"),
		("Access key", "access_key"),
	]
	context.output.table(storage["buckets"], columns, empty="This team has no buckets.")


def list_regions(context: Context, args: argparse.Namespace) -> None:
	storage = context.client.get(f"{STORAGE}.get_object_storage", team=context.client.require_team())
	columns = [("Region", "region"), ("Name", "display_name"), ("Provider", "provider")]
	context.output.table(storage["regions"], columns, empty="No region offers object storage now.")


def create_bucket(context: Context, args: argparse.Namespace) -> None:
	credentials = context.client.post(
		f"{STORAGE}.create_bucket",
		team=context.client.require_team(),
		bucket_name=args.bucket_name,
		region=args.region,
	)
	print_credentials(context, credentials)


def show_usage(context: Context, args: argparse.Namespace) -> None:
	usage = context.client.get(
		f"{STORAGE}.get_bucket_usage", team=context.client.require_team(), name=args.name
	)
	context.output.record(usage)


def rotate_credentials(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Replace the key of {args.name}? The current key stops working at once.", args.yes)
	credentials = context.client.post(
		f"{STORAGE}.rotate_credentials", team=context.client.require_team(), name=args.name
	)
	print_credentials(context, credentials)


def print_credentials(context: Context, credentials: dict) -> None:
	context.output.record(credentials, CREDENTIAL_FIELDS)
	if not context.output.is_json:
		context.output.line("\nSave the secret key now. Central does not show it again.")


def delete_bucket(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Delete bucket {args.name} and its key?", args.yes)
	result = context.client.post(
		f"{STORAGE}.delete_bucket", team=context.client.require_team(), name=args.name
	)
	context.output.result(result, f"Deleted bucket {args.name}.")
