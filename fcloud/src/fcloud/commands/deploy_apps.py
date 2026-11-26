import typer

from fcloud.central import Central
from fcloud.commands.deploy import Branch, Repository, Team, get_app
from fcloud.commands.teams import choose_team
from fcloud.deploy.app import DeployApp
from fcloud.output import get_status_text, print_success, print_table

app = typer.Typer(
	help="Manage your deploy apps: repository branches that deploy on push.", no_args_is_help=True
)


@app.command("list")
def list_deploy_apps(context: typer.Context, team: Team = None) -> None:
	"""List a team's deploy apps, newest first."""
	central = Central.connect(context.obj)
	deploy_apps = DeployApp.get_all(central, team or choose_team(central))
	if not deploy_apps:
		typer.echo("No deploy apps yet. Run `fcloud launch` in a repository.")
		return

	rows = [
		[
			deploy_app.name,
			deploy_app.label,
			get_status_text(deploy_app.status),
			deploy_app.region or "-",
			deploy_app.url or "-",
		]
		for deploy_app in deploy_apps
	]
	print_table(["NAME", "REPOSITORY", "STATUS", "REGION", "URL"], rows)


@app.command()
def disable(context: typer.Context, repository: Repository = None, branch: Branch = None) -> None:
	"""Stop deploying the app on push. Its server keeps running."""
	deploy_app = get_app(context, repository, branch)
	deploy_app.disable()
	print_success(f"Disabled {deploy_app.label}. Pushes no longer deploy it, and its server keeps running.")
	typer.echo("Run `fcloud launch` to connect it again.")
