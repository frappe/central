import argparse

from frappe_cloud.commands import add_command, add_group
from frappe_cloud.context import Context
from frappe_cloud.errors import CentralError


def register(subparsers: argparse._SubParsersAction) -> None:
	commands = add_group(subparsers, "team", "Choose a team and manage its members.")

	add_command(commands, "list", list_teams, "List the teams you belong to.")

	parser = add_command(commands, "use", use_team, "Make a team the default for later commands.")
	parser.add_argument("name", help="Team name, from `fcloud team list`.")

	add_command(commands, "members", list_members, "List the members of the team.")

	parser = add_command(commands, "invite", invite_member, "Invite a person to the team.")
	parser.add_argument("email", help="Email address of the person to invite.")
	parser.add_argument("--role", required=True, help="Role to give, such as Admin or Member.")


def list_teams(context: Context, args: argparse.Namespace) -> None:
	teams = context.client.get("central.api.identity.my_teams")
	for team in teams:
		team["is_default"] = team["name"] == context.client.team

	columns = [
		("Name", "name"),
		("Label", "label"),
		("Role", "role"),
		("Members", "members"),
		("Status", "status"),
		("Default", "is_default"),
	]
	context.output.table(teams, columns, empty="You are not in a team yet.")


def use_team(context: Context, args: argparse.Namespace) -> None:
	# The client has the saved session only for the site that issued it. An API key acts as another user.
	if not context.client.session_id or context.client.is_using_api_key:
		raise CentralError(
			"`fcloud team use` saves a team for the session of `fcloud auth login`, without an API key. "
			"For another site or an API key, pass --team or set FRAPPE_CLOUD_TEAM."
		)

	teams = {team["name"]: team for team in context.client.get("central.api.identity.my_teams")}
	if args.name not in teams:
		raise CentralError(f"You are not in team '{args.name}'. Run `fcloud team list` to see your teams.")

	context.config.team = args.name
	context.config.save()
	context.output.result(teams[args.name], f"Commands now use team {args.name}.")


def list_members(context: Context, args: argparse.Namespace) -> None:
	members = context.client.get("central.api.teams.list_team_members", team=context.client.require_team())
	columns = [
		("User", "user"),
		("Name", "full_name"),
		("Roles", lambda member: sorted({grant["role"] for grant in member["roles"]})),
		("Status", "status"),
		("Owner", "is_owner"),
	]
	context.output.table(members, columns)


def invite_member(context: Context, args: argparse.Namespace) -> None:
	invitation = context.client.post(
		"central.api.teams.invite_team_member",
		team=context.client.require_team(),
		email=args.email,
		role=args.role,
	)
	context.output.result({"invitation": invitation}, f"Invited {args.email} as {args.role}.")
