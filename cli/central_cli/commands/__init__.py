import argparse
import sys
from collections.abc import Callable

from central_cli.context import Context
from central_cli.errors import CentralError

Handler = Callable[[Context, argparse.Namespace], None]

# Every command takes these, so they work after the command name: `central server list --json`.
COMMON_OPTIONS = argparse.ArgumentParser(add_help=False)
COMMON_OPTIONS.add_argument("--url", help="Central URL. Defaults to $CENTRAL_URL, then the saved URL.")
COMMON_OPTIONS.add_argument("--team", help="Team name. Defaults to $CENTRAL_TEAM, then `central team use`.")
COMMON_OPTIONS.add_argument("--json", action="store_true", help="Print the result as JSON.")


def add_group(subparsers: argparse._SubParsersAction, name: str, summary: str) -> argparse._SubParsersAction:
	parser = subparsers.add_parser(name, help=summary, description=summary)
	return parser.add_subparsers(dest="command", required=True, metavar="<command>")


def add_command(
	subparsers: argparse._SubParsersAction, name: str, handler: Handler, summary: str
) -> argparse.ArgumentParser:
	parser = subparsers.add_parser(name, help=summary, description=summary, parents=[COMMON_OPTIONS])
	parser.set_defaults(handler=handler)
	return parser


def add_yes_option(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation.")


def ask(label: str) -> str:
	"""Read one answer from the terminal. A script must pass the value as an option."""
	if not sys.stdin.isatty():
		raise CentralError(f"{label} is required. Pass it as an option.")

	answer = read_answer(f"{label}: ")
	if not answer:
		raise CentralError(f"{label} is required.")
	return answer


def confirm(question: str, is_confirmed: bool) -> None:
	"""Ask before a destructive action. Without a terminal, only --yes confirms."""
	if is_confirmed:
		return
	if not sys.stdin.isatty():
		raise CentralError(f"{question} Pass --yes to confirm.")
	if read_answer(f"{question} [y/N] ").lower() not in ("y", "yes"):
		raise CentralError("Cancelled.")


def read_answer(prompt: str) -> str:
	"""Prompt on standard error, so standard output keeps only the result."""
	print(prompt, end="", file=sys.stderr, flush=True)
	return input().strip()
