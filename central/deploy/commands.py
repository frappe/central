import time

import click
import frappe
from frappe.commands import get_site, pass_context

POLL_SECONDS = 2


@click.command("connect-github-repository")
@click.option("--team", required=True, help="The Team that deploys the repository.")
@click.option(
	"--user", required=True, help="The Central user signed in to the browser that approves on GitHub."
)
@click.option("--repository", required=True, help="owner/name on GitHub. The user must be admin on it.")
@click.option("--branch", help="The branch whose pushes deploy. Defaults to the repository's default branch.")
@pass_context
def connect_github_repository(context, team: str, user: str, repository: str, branch: str | None) -> None:
	"""Deploy a repository for a team, after the user proves on GitHub that they are admin on it."""
	from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
		GitHubDeployAppInstallation,
	)
	from central.deploy.github import GitHubDeployApp

	frappe.init(get_site(context))
	frappe.connect()
	try:
		state = GitHubDeployAppInstallation.start(team, user, repository, branch)
		click.echo(f"Sign in to Central as {user} in your browser, then open:\n")
		click.echo(GitHubDeployApp().get_install_url(state) + "\n")
		click.echo("Waiting for GitHub (Ctrl+C to stop)...")

		while not GitHubDeployAppInstallation.is_verified(state, user):
			time.sleep(POLL_SECONDS)

		app = GitHubDeployAppInstallation.complete(state, user)
		# A command has no request cycle to commit for it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		click.secho(f"Pushes to {app.repository}@{app.branch} now deploy {app.name} for {team}.", fg="green")
	except (frappe.ValidationError, frappe.DoesNotExistError) as error:
		raise click.ClickException(str(error)) from error
	finally:
		frappe.destroy()


commands = [connect_github_repository]
