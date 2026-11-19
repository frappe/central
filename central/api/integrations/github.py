import json
import secrets
import urllib.parse

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.infrastructure.doctype.github_connection.github_connection import (
	GitHubConnection,
	GitHubConnectionAttempt,
)
from central.integrations.github import WEB_URL, GitHubApp, callback_url, convert_manifest
from central.sso import central_url

MANIFEST_TTL_SECONDS = 15 * 60


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def status() -> dict:
	"""Whether this Central offers GitHub App access, and the Pilot's active connections."""
	if not GitHubApp.is_configured():
		return {"available": False, "connections": []}

	return {
		"available": True,
		"connections": [
			{
				"account": connection.account,
				"repositories": [repository.full_name for repository in connection.repositories],
			}
			for connection in GitHubConnection.get_active(frappe.local.pilot_credential)
		],
	}


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def start_connection(return_url: str) -> dict:
	"""A Central link where a user with console access to this server connects GitHub."""
	GitHubApp()
	if urllib.parse.urlsplit(return_url).scheme not in ("http", "https"):
		frappe.throw(_("The return URL must start with http:// or https://."), frappe.ValidationError)

	attempt = GitHubConnectionAttempt.start(frappe.local.pilot_credential, return_url)
	return {"url": f"{central_url()}/dashboard/github/connect/{attempt.attempt_id}"}


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def repositories() -> list[dict]:
	"""The repositories granted to this Pilot, with no credentials."""
	app = GitHubApp()
	return [
		repository
		for connection in GitHubConnection.get_active(frappe.local.pilot_credential)
		for repository in app.get_installation_repositories(connection.installation_id)
		if repository["repository_id"] in {granted.repository_id for granted in connection.repositories}
	]


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def repository_token(repository: str) -> dict:
	"""A read-only token for one granted repository (`owner/name`). It expires in about an hour."""
	connection, repository_id = GitHubConnection.find_repository(frappe.local.pilot_credential, repository)
	version = connection.version
	token = GitHubApp().create_installation_token(connection.installation_id, repository_id)

	# The grant can change while GitHub mints the token.
	if not connection.is_current(version):
		frappe.throw(_("The GitHub grant changed. Try again."), frappe.PermissionError)

	frappe.local.response_headers["Cache-Control"] = "no-store"
	return token


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def disconnect() -> None:
	"""Remove every GitHub grant of this Pilot. Tokens already issued stay valid until they expire."""
	for connection in GitHubConnection.get_active(frappe.local.pilot_credential):
		connection.disable()


@frappe.whitelist(methods=["GET"])
def get_connection_attempt(attempt: str) -> dict:
	"""What the connect page shows: the server, and the user's installations once GitHub authorized."""
	return_url = GitHubConnectionAttempt.find_return_url(attempt)
	connection_attempt = GitHubConnectionAttempt.find(attempt)
	if not connection_attempt:
		return {"is_expired": True, "return_url": return_url}

	credential = connection_attempt.bind(frappe.session.user)
	app = GitHubApp()

	user_token = connection_attempt.user_token
	return {
		"is_expired": False,
		"return_url": return_url,
		"server": frappe.db.get_value("Virtual Machine", credential.server, "title")
		if credential.server
		else "",
		"team": frappe.db.get_value("Team", credential.team, "team_name"),
		"is_authorized": bool(user_token),
		"authorize_url": app.get_authorize_url(connection_attempt.state, connection_attempt.code_challenge),
		"install_url": app.get_install_url(connection_attempt.state),
		"installations": app.get_user_installations(user_token) if user_token else [],
		"granted_repository_ids": [
			repository.repository_id
			for connection in GitHubConnection.get_active(credential)
			for repository in connection.repositories
		],
	}


@frappe.whitelist(methods=["GET"])
def get_installation_repositories(attempt: str, installation_id: str) -> list[dict]:
	"""The repositories of one installation the user can see. Only an admin repository can be granted."""
	connection_attempt = GitHubConnectionAttempt.load(attempt)
	connection_attempt.bind(frappe.session.user)
	return GitHubApp().get_user_repositories(connection_attempt.require_user_token(), installation_id)


@frappe.whitelist(methods=["POST"])
def complete_connection(attempt: str, grants: dict[str, list[str]] | str) -> dict:
	"""Grant the selected repositories of each installation. An installation sent empty loses its grant."""
	grants = json.loads(grants) if isinstance(grants, str) else grants
	if not isinstance(grants, dict) or not all(isinstance(ids, list) for ids in grants.values()):
		frappe.throw(_("Send the selected repositories of each GitHub account."))

	connection_attempt = GitHubConnectionAttempt.load(attempt)
	connection_attempt.bind(frappe.session.user)
	connection_attempt.complete(grants)
	return {"return_url": GitHubConnectionAttempt.find_return_url(attempt)}


# nosemgrep: guest-whitelisted-method -- the OAuth state binds the callback to the attempt and its user.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def oauth_callback(state: str, code: str | None = None, **kwargs) -> None:
	"""GitHub returns here after an authorize or install. Only the attempt's user gets the token."""
	attempt_id = GitHubConnectionAttempt.find_attempt_id(state)
	if not attempt_id:
		return _redirect("/dashboard/github/connect")

	connection_attempt = GitHubConnectionAttempt.find(attempt_id)
	if code and connection_attempt and frappe.session.user == connection_attempt.user:
		connection_attempt.set_user_token(GitHubApp().exchange_code(code, connection_attempt.code_verifier))

	# The connect page sends the user straight to GitHub unless GitHub came back without a code.
	_redirect(f"/dashboard/github/connect/{attempt_id}{'' if code else '?cancelled=1'}")


# nosemgrep: guest-whitelisted-method -- the HMAC signature authenticates GitHub.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook() -> None:
	"""Disable or narrow grants when an installation is removed or loses repositories."""
	app = GitHubApp()
	if not app.is_valid_webhook_signature(
		frappe.request.get_data(), frappe.get_request_header("X-Hub-Signature-256")
	):
		frappe.throw(_("Invalid webhook signature."), frappe.AuthenticationError)

	event = frappe.get_request_header("X-GitHub-Event")
	payload = json.loads(frappe.request.get_data())
	installation_id = str(payload.get("installation", {}).get("id", ""))

	if event == "installation" and payload.get("action") in ("deleted", "suspend"):
		GitHubConnection.disable_installation(installation_id)
	elif event == "installation_repositories" and payload.get("action") == "removed":
		removed = {str(repository["id"]) for repository in payload.get("repositories_removed", [])}
		GitHubConnection.remove_repositories(installation_id, removed)
	elif event == "repository" and payload.get("action") == "renamed":
		repository = payload["repository"]
		GitHubConnection.rename_repository(installation_id, str(repository["id"]), repository["full_name"])


@frappe.whitelist(methods=["POST"])
def create_app_manifest(app_name: str, organization: str | None = None) -> dict:
	"""The form GitHub needs to create the App from a manifest. System Manager only."""
	frappe.only_for("System Manager")

	state = secrets.token_urlsafe(24)
	frappe.cache.set_value(
		f"github:manifest-state:{state}", frappe.session.user, expires_in_sec=MANIFEST_TTL_SECONDS
	)

	base_url = central_url()
	manifest = {
		"name": app_name,
		"url": base_url,
		"hook_attributes": {"url": f"{base_url}/api/method/central.api.integrations.github.webhook"},
		"redirect_url": f"{base_url}/api/method/central.api.integrations.github.manifest_callback",
		"callback_urls": [callback_url()],
		"request_oauth_on_install": True,
		"public": True,
		"default_permissions": {"contents": "read", "metadata": "read"},
		"default_events": ["repository"],
	}
	owner = f"organizations/{urllib.parse.quote(organization)}/" if organization else ""
	return {"action": f"{WEB_URL}/{owner}settings/apps/new?state={state}", "manifest": json.dumps(manifest)}


@frappe.whitelist(methods=["GET"])
def manifest_callback(code: str, state: str) -> None:
	"""GitHub returns here after the App is created. Save its credentials to Central Settings."""
	frappe.only_for("System Manager")
	key = f"github:manifest-state:{state}"
	if frappe.cache.get_value(key) != frappe.session.user:
		frappe.throw(
			_("This GitHub App setup has expired. Start again from Central Settings."), frappe.PermissionError
		)
	frappe.cache.delete_value(key)

	app = convert_manifest(code)
	settings = frappe.get_doc("Central Settings")
	settings.update(
		{
			"github_app_id": str(app["id"]),
			"github_app_slug": app["slug"],
			"github_client_id": app["client_id"],
			"github_client_secret": app["client_secret"],
			"github_webhook_secret": app["webhook_secret"],
			"github_private_key": app["pem"],
		}
	)
	settings.save()
	# GitHub redirects with a GET, which Frappe rolls back, and its code works only once.
	# The one-use state bound to this user's session stands in for the CSRF check.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit, whitelisted-side-effect-on-get
	_redirect("/app/central-settings")


def _redirect(location: str) -> None:
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = location
