import urllib.parse
from typing import Annotated

import httpx2
import typer
from rich.text import Text

from fcloud.auth.credentials import ApiKeyCredential, Credential, OAuthCredential
from fcloud.central import Central
from fcloud.errors import FcloudError
from fcloud.output import print_success, print_table, print_warning
from fcloud.profiles import Profile, ProfileStore

app = typer.Typer(help="Log in to Central and manage profiles.", no_args_is_help=True)


@app.command()
def login(
	url: str,
	api_key: Annotated[bool, typer.Option("--api-key", help="Ask for an API key and secret.")] = False,
	name: Annotated[str | None, typer.Option(help="Profile name. Defaults to the URL's host.")] = None,
	default: Annotated[bool, typer.Option("--default", help="Make this the default profile.")] = False,
) -> None:
	"""Sign in to Central in the browser, or with an API key, and keep the credentials in the system keyring."""
	url = url.rstrip("/") if url.startswith(("http://", "https://")) else f"https://{url.rstrip('/')}"
	name = name or urllib.parse.urlparse(url).hostname
	store = ProfileStore()

	if api_key:
		profile, credential = Profile(name, url, "api_key"), read_api_key()
		profile.set_secret(credential.to_secret())
	else:
		previous = store.profiles.get(name)
		# Reuse the client registered for this site, because Frappe rate limits registration.
		client_id = previous.client_id if previous and previous.url == url else None
		credential = OAuthCredential.log_in(name, url, client_id)
		profile = credential.profile

	store.save(profile, make_default=default)
	print_success(f"Logged in to {url} as {Central(url, credential).get_user()} (profile {name}).")


def read_api_key() -> Credential:
	api_key = typer.prompt("API key").strip()
	api_secret = typer.prompt("API secret", hide_input=True).strip()
	if not api_key.isalnum() or not api_secret.isalnum():
		raise FcloudError("The API key and secret are letters and digits only.")
	return ApiKeyCredential(api_key, api_secret)


@app.command()
def logout(name: str) -> None:
	"""Revoke the profile's session and remove its credentials."""
	store = ProfileStore()
	profile = store.get(name)
	if profile.method == "oauth":
		try:
			OAuthCredential.from_profile(profile).revoke()
		except (FcloudError, httpx2.HTTPError) as error:
			print_warning(f"Couldn't revoke the session on Central ({error}). Removing it here anyway.")

	profile.delete_secret()
	store.remove(name)
	print_success(f"Removed {name}.")


@app.command("list")
def list_profiles() -> None:
	"""List profiles. * marks the default."""
	store = ProfileStore()
	rows = [
		[
			Text("*" if profile.name == store.default_name else "", style="bold green"),
			profile.name,
			profile.method,
			profile.url,
		]
		for profile in store.profiles.values()
	]
	if rows:
		print_table(["", "PROFILE", "METHOD", "URL"], rows)
	else:
		typer.echo("No profiles. Run `fcloud auth login <url>`.")


@app.command()
def default(name: str) -> None:
	"""Set the default profile."""
	ProfileStore().set_default(name)
	typer.echo(f"Default profile: {name}.")


@app.command()
def whoami(context: typer.Context) -> None:
	"""Show the user of the active profile."""
	central = Central.connect(context.obj)
	typer.echo(f"{central.get_user()} on {central.url}")
