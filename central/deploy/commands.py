import time

import click
import frappe
from frappe.commands import get_site, pass_context

POLL_SECONDS = 2


@click.command("connect-github-deploy")
@click.option("--team", required=True, help="The Team the installation is linked to.")
@click.option(
	"--user", required=True, help="The Central user signed in to the browser that installs the App."
)
@pass_context
def connect_github_deploy(context, team: str, user: str) -> None:
	"""Link a GitHub Deploy App installation to a team, without the console."""
	from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
		GitHubDeployAppInstallation,
	)
	from central.deploy.github import GitHubDeployApp

	frappe.init(get_site(context))
	frappe.connect()
	try:
		state = GitHubDeployAppInstallation.start(team, user)
		click.echo(f"Sign in to Central as {user} in your browser, then open:\n")
		click.echo(GitHubDeployApp().get_install_url(state) + "\n")
		click.echo("Waiting for GitHub (Ctrl+C to stop)...")

		while not GitHubDeployAppInstallation.is_verified(state, user):
			time.sleep(POLL_SECONDS)

		installation = GitHubDeployAppInstallation.complete(state, user)
		# A command has no request cycle to commit for it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		click.secho(
			f"Linked {installation.account} (installation {installation.installation_id}) to {team}.",
			fg="green",
		)
	except (frappe.PermissionError, frappe.DoesNotExistError) as error:
		raise click.ClickException(str(error)) from error
	finally:
		frappe.destroy()


@click.command("connect-github-repository")
@click.option("--team", required=True, help="The Team that deploys the repository.")
@click.option("--repository", required=True, help="owner/name on GitHub.")
@click.option("--branch", help="The branch whose pushes deploy. Defaults to the repository's default branch.")
@pass_context
def connect_github_repository(context, team: str, repository: str, branch: str | None) -> None:
	"""Deploy a repository the team's GitHub installation can access."""
	from central.deploy.doctype.deploy_app.deploy_app import DeployApp

	frappe.init(get_site(context))
	frappe.connect()
	try:
		app = DeployApp.add(team, repository, branch)
		# A command has no request cycle to commit for it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		click.secho(f"Pushes to {app.repository}@{app.branch} now deploy {app.name} for {team}.", fg="green")
	except (frappe.ValidationError, frappe.DoesNotExistError) as error:
		raise click.ClickException(str(error)) from error
	finally:
		frappe.destroy()


commands = [connect_github_deploy, connect_github_repository]
