from typing import Annotated

import httpx2
import typer

from fcloud import __version__
from fcloud.commands import auth, deploy, deploy_apps, teams
from fcloud.errors import FcloudError
from fcloud.output import print_error

app = typer.Typer(
	name="fcloud",
	help="Frappe Cloud from the command line.",
	no_args_is_help=True,
	pretty_exceptions_enable=False,
	context_settings={"help_option_names": ["-h", "--help"]},
)
# The top level acts on the deploy app in the working directory. Every other resource is a noun group with verbs.
# See "Command naming" in README.md.
app.command("launch")(deploy.launch)
app.command("deploys")(deploy.list_deploys)
app.command("logs")(deploy.logs)
app.add_typer(deploy.secrets, name="secrets")
app.add_typer(deploy_apps.app, name="deploy-apps")
app.add_typer(teams.app, name="teams")
app.add_typer(auth.app, name="auth")


def print_version(value: bool) -> None:
	if value:
		typer.echo(f"fcloud {__version__}")
		raise typer.Exit()


@app.callback()
def root(
	context: typer.Context,
	profile: Annotated[
		str | None, typer.Option("--profile", "-p", help="Profile to use instead of the default.")
	] = None,
	version: Annotated[
		bool, typer.Option("--version", callback=print_version, is_eager=True, help="Show the version.")
	] = False,
) -> None:
	context.obj = profile


def main(arguments: list[str] | None = None) -> None:
	try:
		app(args=arguments, prog_name="fcloud")
	except FcloudError as error:
		print_error(error.message)
		raise SystemExit(1)
	except httpx2.HTTPError as error:
		print_error(f"Can't reach Central: {error}")
		raise SystemExit(1)
