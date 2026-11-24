import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
	GitHubDeployAppInstallation,
)
from central.deploy.github import GitHubDeployApp

DELIVERY_TTL_SECONDS = 24 * 60 * 60
BRANCH_REF_PREFIX = "refs/heads/"
AGENT_TOKEN_HEADER = "X-Deploy-Agent-Token"
BUILD_REPORT_STATES = ("Running", "Succeeded", "Failed")
RELEASE_REPORT_STATES = ("Releasing", "Live", "Failed")


@frappe.whitelist(methods=["POST"])
def connect_repository(team: str, repository: str, region: str, branch: str | None = None) -> dict:
	"""Start deploying `repository` (owner/name) for `team`. The user signs in to GitHub at `sign_in_url`, and
	installs the App there when it can't reach the repository yet, then finishes with
	complete_repository_connection and the same `state`."""
	state = GitHubDeployAppInstallation.start(team, frappe.session.user, repository, region, branch)
	return {
		"state": state,
		"sign_in_url": GitHubDeployAppInstallation.get_sign_in_url(state, frappe.session.user),
	}


@frappe.whitelist(methods=["POST"])
def complete_repository_connection(state: str) -> dict:
	"""Create the Deploy App once GitHub returned from the install; pushes to its branch deploy from then on."""
	app = GitHubDeployAppInstallation.complete(state, frappe.session.user)
	return {"name": app.name, "repository": app.repository, "branch": app.branch, "domain": app.domain}


@frappe.whitelist(methods=["GET"])
def get_deploy_request(name: str) -> dict:
	"""One deploy with its pipeline tasks, and the build and release output. The console polls it while the
	deploy runs; a failed task's message is the deploy's `error`."""
	request: DeployRequest = frappe.get_doc("Deploy Request", name)
	request.check_permission("read")
	pipelines = frappe.get_all(
		"Pipeline", filters={"linked_doctype": request.doctype, "linked_docname": request.name}, pluck="name"
	)
	return {
		"name": request.name,
		"deploy_app": request.deploy_app,
		"commit": request.commit,
		"status": request.status,
		"error": request.error,
		"creation": request.creation,
		"tasks": frappe.get_all(
			"Pipeline Task",
			filters={"pipeline": ["in", pipelines]},
			fields=["method_title", "status", "start", "end"],
			order_by="creation asc",
		),
		"build_log": request.get_log("build_log"),
		"release_log": request.get_log("release_log"),
	}


# nosemgrep: guest-whitelisted-method -- the state binds the callback to the user who started it.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def oauth_callback(
	state: str | None = None, code: str | None = None, installation_id: str | None = None, **kwargs
) -> None:
	"""GitHub returns here after the sign-in or an install. An install started on github.com has no state to link."""
	if not (state and code):
		return frappe.respond_as_web_page(
			_("Nothing to connect"),
			_("Start the connection from Frappe Cloud, then sign in to GitHub from the link it gives."),
			indicator_color="orange",
		)

	if not GitHubDeployAppInstallation.verify(state, code, installation_id, frappe.session.user):
		# GitHub shows its install page, or its configure page when the App is on the account already.
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = GitHubDeployApp().get_install_url(state)
		return

	frappe.respond_as_web_page(
		_("GitHub connected"),
		_("Go back to where you started to finish connecting it."),
		indicator_color="green",
	)


# nosemgrep: guest-whitelisted-method -- the HMAC signature authenticates GitHub.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook() -> None:
	"""Events of the deploy App. Each delivery is handled once; a push queues a deploy of each matching app."""
	body = frappe.request.get_data()
	if not GitHubDeployApp().is_valid_webhook_signature(
		body, frappe.get_request_header("X-Hub-Signature-256")
	):
		frappe.throw(_("Invalid webhook signature."), frappe.AuthenticationError)

	delivery = frappe.get_request_header("X-GitHub-Delivery")
	if not delivery:
		frappe.throw(_("Missing X-GitHub-Delivery header."))
	key = frappe.cache.make_key(f"github-deploy:delivery:{delivery}")
	# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix.
	if not frappe.cache.set(key, 1, nx=True, ex=DELIVERY_TTL_SECONDS):
		return

	event = frappe.get_request_header("X-GitHub-Event")
	payload = json.loads(body)
	if event == "push":
		for app in get_deploy_apps(payload):
			DeployRequest.queue(app, payload["after"], delivery)


def get_deploy_apps(push: dict) -> list[str]:
	"""The apps a push deploys. A tag push or a deleted branch deploys nothing."""
	ref = push.get("ref", "")
	if not ref.startswith(BRANCH_REF_PREFIX) or push.get("deleted"):
		return []

	return DeployApp.get_for_push(
		str(push["installation"]["id"]), str(push["repository"]["id"]), ref.removeprefix(BRANCH_REF_PREFIX)
	)


# nosemgrep: guest-whitelisted-method -- the app's agent token authenticates the deploy agent.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_build() -> dict | None:
	"""The app's newest build the agent hasn't reported on yet. Changes nothing; only report_build sets the build status."""
	app = DeployApp.get_for_agent(frappe.get_request_header(AGENT_TOKEN_HEADER) or "")
	name = frappe.db.get_value(
		"Deploy Request",
		{"deploy_app": app.name, "status": "Building", "build_status": ["is", "not set"]},
		order_by="creation desc",
	)
	if not name:
		return None

	request: DeployRequest = frappe.get_doc("Deploy Request", name)
	return request.get_build_payload()


# nosemgrep: guest-whitelisted-method -- the app's agent token authenticates the deploy agent.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_build(deploy_request: str, status: str, log: str = "") -> dict:
	"""Save what the agent says about a build it got from get_build, and add the log lines it sent since its last
	report. `cancel` tells it a newer push replaced the build."""
	app = DeployApp.get_for_agent(frappe.get_request_header(AGENT_TOKEN_HEADER) or "")
	if status not in BUILD_REPORT_STATES:
		frappe.throw(_("Unknown build status {0}.").format(status))

	request: DeployRequest = frappe.get_doc("Deploy Request", deploy_request, for_update=True)
	if request.deploy_app != app.name:
		frappe.throw(_("This build belongs to another app."), frappe.PermissionError)
	if request.status != "Building":
		return {"cancel": True}

	request.build_status = status
	request.build_reported_at = now_datetime()
	request.append_log("build_log", log)
	# The agent reports on the team's build; no Desk user owns it.
	request.save(ignore_permissions=True)
	return {"cancel": False}


# nosemgrep: guest-whitelisted-method -- the app's agent token authenticates the deploy agent.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_deployment_status(deploy_request: str, status: str, logs: str = "") -> None:
	"""Save what the agent says about a release it started after the build. Nothing cancels a release; when the new
	container fails its health check, the agent removes it, keeps its logs, and the old one keeps serving."""
	app = DeployApp.get_for_agent(frappe.get_request_header(AGENT_TOKEN_HEADER) or "")
	if status not in RELEASE_REPORT_STATES:
		frappe.throw(_("Unknown release status {0}.").format(status))

	request: DeployRequest = frappe.get_doc("Deploy Request", deploy_request, for_update=True)
	if request.deploy_app != app.name:
		frappe.throw(_("This release belongs to another app."), frappe.PermissionError)

	request.release_status = status
	request.release_reported_at = now_datetime()
	request.append_log("release_log", logs)
	# The agent reports on the team's release; no Desk user owns it.
	request.save(ignore_permissions=True)
