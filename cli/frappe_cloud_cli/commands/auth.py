import argparse
import sys

from frappe_cloud_cli.client import CentralClient
from frappe_cloud_cli.commands import add_command, add_group, ask
from frappe_cloud_cli.context import Context
from frappe_cloud_cli.errors import CentralError


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "auth", "Sign in and out of Central.")

	parser = add_command(commands, "login", login, "Sign in with a code sent to your email.")
	parser.add_argument("--email", help="Your email address.")

	add_command(commands, "logout", logout, "Sign out and forget the saved session.")
	add_command(commands, "whoami", whoami, "Show the signed-in user.")


def login(context: Context, args: argparse.Namespace) -> None:
	client = context.client
	email = args.email or ask("Email")
	client.call("POST", "central.api.auth.send_code", {"email": email}, is_guest=True)
	print(f"We sent a sign-in code to {email}.", file=sys.stderr)

	code = ask("Code")
	result = verify_code(context, email, code)
	if result.get("needs_name"):
		result = verify_code(context, email, code, full_name=ask("Full name"))
	if not client.session_id:
		raise CentralError("Central did not start a session. Try again.")

	config = context.config
	config.clear_session()
	config.url = client.url
	config.user = result["user"]
	config.session_id = client.session_id
	config.csrf_token = result.get("csrf_token")
	config.save()

	context.output.result(
		{"user": config.user, "url": config.url}, f"Signed in to {config.url} as {config.user}."
	)


def verify_code(context: Context, email: str, code: str, full_name: str | None = None) -> dict:
	params = {"email": email, "code": code, "full_name": full_name}
	return context.client.call("POST", "central.api.auth.verify_code", params, is_guest=True)


def logout(context: Context, args: argparse.Namespace) -> None:
	config = context.config
	if config.session_id:
		# Send the saved session only: an API key in the environment would end nothing.
		session = CentralClient(
			context.client.url, session_id=config.session_id, csrf_token=config.csrf_token
		)
		try:
			session.post("logout")
		except CentralError:
			# An expired session has nothing left to end on the server. The local copy goes either way.
			pass

	config.clear_session()
	config.save()
	context.output.result({"user": None}, "Signed out.")


def whoami(context: Context, args: argparse.Namespace) -> None:
	profile = context.client.get("central.api.identity.my_profile")
	profile["team"] = context.client.team
	profile["url"] = context.client.url
	context.output.record(
		profile, [("User", "user"), ("Name", "full_name"), ("Team", "team"), ("URL", "url")]
	)
