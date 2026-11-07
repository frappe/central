import argparse

from frappe_cloud.commands import add_command, add_group, add_yes_option, confirm
from frappe_cloud.context import Context

AI = "central.services.api.ai"


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "ai", "Use hosted LLM models through team API keys.")

	add_command(commands, "status", show_status, "Show whether AI is on, and the team's spend.")
	add_command(commands, "enable", enable_ai, "Turn AI on for the team.")

	parser = add_command(commands, "models", list_models, "List the models the team's keys may call.")
	parser.add_argument("--geography", help="Geography of the gateway. Defaults to the default one.")

	add_command(commands, "keys", list_keys, "List the team's API keys.")

	parser = add_command(commands, "create-key", create_key, "Create an API key and print its secret once.")
	parser.add_argument("label", help="A name to identify the key.")
	parser.add_argument("--cap", type=int, required=True, help="Monthly spend cap in whole US dollars.")
	parser.add_argument("--geography", help="Geography of the gateway. Defaults to the default one.")

	parser = add_command(commands, "revoke-key", revoke_key, "Revoke an API key.")
	parser.add_argument("key", help="Key name, from `fcloud ai keys`.")
	add_yes_option(parser)

	parser = add_command(commands, "usage", show_usage, "Show requests and cost over a period.")
	parser.add_argument("--period", default="Last 7 Days", help="Period, such as 'Last 30 Days'.")
	parser.add_argument("--key", help="Only this key's usage.")


def show_status(context: Context, args: argparse.Namespace) -> None:
	context.output.record(context.client.get(f"{AI}.get_ai", team=context.client.require_team()))


def enable_ai(context: Context, args: argparse.Namespace) -> None:
	result = context.client.post(f"{AI}.enable_ai", team=context.client.require_team())
	context.output.result(result, "AI is on for the team.")


def list_models(context: Context, args: argparse.Namespace) -> None:
	models = context.client.get(
		f"{AI}.get_models", team=context.client.require_team(), geography=args.geography
	)
	context.output.table(models, [(key, key) for key in (models[0] if models else {})], empty="No models.")


def list_keys(context: Context, args: argparse.Namespace) -> None:
	keys = context.client.get(f"{AI}.list_api_keys", team=context.client.require_team())
	columns = [
		("Name", "name"),
		("Title", "title"),
		("Key", "masked"),
		("Status", "status"),
		("Geography", "geography"),
		("Cap USD", "cap"),
		("Spent USD", "month_spent"),
	]
	context.output.table(keys, columns, empty="This team has no API keys.")


def create_key(context: Context, args: argparse.Namespace) -> None:
	key = context.client.post(
		f"{AI}.create_api_key",
		team=context.client.require_team(),
		label=args.label,
		geography=args.geography,
		cap=args.cap,
	)
	fields = [
		("Name", "name"),
		("Geography", "geography"),
		("Gateway", "gateway_url"),
		("API key", "api_key"),
	]
	context.output.record(key, fields)
	if not context.output.is_json:
		context.output.line("\nSave the API key now. Central does not show it again.")


def revoke_key(context: Context, args: argparse.Namespace) -> None:
	confirm(f"Revoke API key {args.key}? Requests with it stop at once.", args.yes)
	result = context.client.post(f"{AI}.revoke_api_key", team=context.client.require_team(), key=args.key)
	context.output.result(result, f"Revoked {args.key}.")


def show_usage(context: Context, args: argparse.Namespace) -> None:
	usage = context.client.get(
		f"{AI}.get_usage", team=context.client.require_team(), period=args.period, key=args.key
	)
	context.output.record(usage)
