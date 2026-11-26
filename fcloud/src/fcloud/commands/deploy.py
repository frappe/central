import time
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.text import Text

from fcloud.central import Central
from fcloud.commands.teams import choose_team
from fcloud.deploy.app import DeployApp, RepositoryConnection
from fcloud.deploy.logs import POLL_SECONDS, DeployLog
from fcloud.deploy.repository import get_target, has_container_file
from fcloud.errors import FcloudError
from fcloud.output import console, get_status_text, print_success, print_table, print_warning

secrets = typer.Typer(help="Manage the environment variables the app's container gets.", no_args_is_help=True)

Repository = Annotated[
	str | None, typer.Option(help="owner/name. Defaults to the origin of the working directory.")
]
Branch = Annotated[str | None, typer.Option(help="Defaults to the current branch.")]
Team = Annotated[str | None, typer.Option(help="Defaults to your only team, or asks when you have several.")]


def get_app(context: typer.Context, repository: str | None, branch: str | None) -> DeployApp:
	return DeployApp.find(Central.connect(context.obj), *get_target(repository, branch))


def launch(
	context: typer.Context,
	region: Annotated[str, typer.Option(help="Region to run the app in.")],
	team: Team = None,
	repository: Repository = None,
	branch: Branch = None,
) -> None:
	"""Connect the repository and branch. Each push to the branch then deploys it."""
	central = Central.connect(context.obj)
	# With --repository and no --branch, Central deploys the repository's default branch.
	repository, branch = get_target(repository, branch)
	if not has_container_file(Path.cwd()):
		print_warning("No Dockerfile or Containerfile here. The deploy fails without one.")

	connection = RepositoryConnection.start(central, team or choose_team(central), repository, region, branch)
	typer.echo(
		f"Sign in to GitHub, in a browser signed in to Central as the CLI's user:\n\n  {connection.sign_in_url}\n\n"
		f"If the GitHub App can't reach {repository} yet, GitHub asks you to install it or add the repository.\n"
		"If the App is installed without commit status access, an owner of the account accepts its new permissions.\n"
	)
	webbrowser.open(connection.sign_in_url)

	typer.echo("Waiting for GitHub (Ctrl+C to stop)...")
	while (deploy_app := connection.get_app()) is None:
		time.sleep(POLL_SECONDS)
	print_success(f"\nConnected {deploy_app.label} as {deploy_app.name}. It will be live at {deploy_app.url}")
	typer.echo(f"Push to {deploy_app.branch} to deploy. Then: fcloud logs --follow")


def list_deploys(
	context: typer.Context,
	limit: int = 20,
	repository: Repository = None,
	branch: Branch = None,
) -> None:
	"""List the app's deploys, newest first."""
	deploy_app = get_app(context, repository, branch)
	deploys = deploy_app.get_deploys(limit=limit)
	console.print(Text.assemble((deploy_app.label, "bold"), f"  {deploy_app.url or ''}\n"))
	if not deploys:
		typer.echo("No deploys yet. Push to the branch to start one.")
		return

	rows = [
		[
			deploy["name"],
			deploy["commit"][:8],
			get_status_text(deploy["status"]),
			deploy["creation"][:19],
			Text(deploy.get("error") or "", style="red"),
		]
		for deploy in deploys
	]
	print_table(["DEPLOY", "COMMIT", "STATUS", "CREATED", "ERROR"], rows)


def logs(
	context: typer.Context,
	deploy_request: Annotated[str | None, typer.Argument(help="Defaults to the newest deploy.")] = None,
	follow: Annotated[bool, typer.Option("--follow", "-f", help="Poll until the deploy finishes.")] = False,
	repository: Repository = None,
	branch: Branch = None,
) -> None:
	"""Show a deploy's tasks and logs."""
	if deploy_request:
		central = Central.connect(context.obj)
	else:
		deploy_app = get_app(context, repository, branch)
		central, deploy_request = deploy_app.central, deploy_app.get_latest_deploy_name()

	deploy = DeployLog(central, deploy_request).show(follow=follow)
	if deploy["status"] == "Failed":
		raise FcloudError(f"Deploy failed: {deploy['error']}")
	if deploy["status"] == "Succeeded":
		print_success("\nLive.")


@secrets.command("list")
def list_secrets(context: typer.Context, repository: Repository = None, branch: Branch = None) -> None:
	"""List the secret names."""
	names = get_app(context, repository, branch).get_secret_names()
	typer.echo("\n".join(names) if names else "No secrets. Run `fcloud secrets set KEY`.")


@secrets.command("set")
def set_secrets(
	context: typer.Context,
	items: Annotated[
		list[str], typer.Argument(metavar="KEY[=VALUE]...", help="A bare KEY asks for its value.")
	],
	repository: Repository = None,
	branch: Branch = None,
) -> None:
	"""Set secrets. A bare KEY asks for its value, so the value stays out of the shell history."""
	values = {}
	for item in items:
		name, separator, value = item.partition("=")
		values[name] = value if separator else typer.prompt(name, hide_input=True)
	print_secret_names(get_app(context, repository, branch), secrets=values)


@secrets.command("unset")
def unset_secrets(
	context: typer.Context,
	names: Annotated[list[str], typer.Argument(metavar="KEY...")],
	repository: Repository = None,
	branch: Branch = None,
) -> None:
	"""Remove secrets."""
	print_secret_names(get_app(context, repository, branch), unset=names)


def print_secret_names(deploy_app: DeployApp, **change) -> None:
	names = deploy_app.update_secrets(**change)
	typer.echo(f"Secrets of {deploy_app.label}: {', '.join(names) or 'none'}.")
	typer.echo("The container gets them on the next push.")
