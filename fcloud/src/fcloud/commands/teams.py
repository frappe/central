import sys

import typer

from fcloud.central import Central
from fcloud.errors import FcloudError
from fcloud.output import print_table

app = typer.Typer(help="Manage your teams.", no_args_is_help=True)


@app.command("list")
def list_teams(context: typer.Context) -> None:
	"""List your active teams."""
	teams = Central.connect(context.obj).get_teams()
	print_table(["TEAM", "NAME", "ROLE"], [[team["name"], team["label"], team["role"]] for team in teams])


def choose_team(central: Central) -> str:
	"""The user's only team, or the one they pick when they have several."""
	teams = central.get_teams()
	if not teams:
		raise FcloudError("Your user is not an active member of any team.")
	if len(teams) == 1:
		typer.echo(f"Team: {teams[0]['label']} ({teams[0]['name']})")
		return teams[0]["name"]
	if not sys.stdin.isatty():
		raise FcloudError("Pass --team. Your teams: " + ", ".join(team["name"] for team in teams))

	for number, team in enumerate(teams, 1):
		typer.echo(f"  {number}. {team['label']} ({team['name']}, {team['role']})")
	choice = typer.prompt("Team number", type=typer.IntRange(1, len(teams)))
	return teams[choice - 1]["name"]
