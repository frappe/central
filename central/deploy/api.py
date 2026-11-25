import frappe
from frappe import _
from frappe.utils import now_datetime

from central.deploy.connection import DeployConnectionAttempt
from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.deploy.doctype.deploy_request.deploy_request import FINISHED_STATES, DeployRequest
from central.iam import can

DELIVERY_TTL_SECONDS = 24 * 60 * 60
BRANCH_REF_PREFIX = "refs/heads/"
AGENT_TOKEN_HEADER = "X-Deploy-Agent-Token"
BUILD_REPORT_STATES = ("Running", "Succeeded", "Failed")
RELEASE_REPORT_STATES = ("Releasing", "Live", "Failed")


# Frist Step
@frappe.whitelist(methods=["POST"])
def connect_repository(team: str, repository: str, region: str, branch: str | None = None) -> dict:
	"""Start deploying `repository` (owner/name) for `team`. The user signs in to GitHub at `sign_in_url`, and
	installs the App there when it can't reach the repository yet, then finishes with
	complete_repository_connection and the same `state`."""
	state = DeployConnectionAttempt.start(team, frappe.session.user, repository, region, branch)
	return {
		"state": state,
		"sign_in_url": DeployConnectionAttempt.get_sign_in_url(state, frappe.session.user),
	}


# Finally finish the connection and create the deploy app
@frappe.whitelist(methods=["POST"])
def complete_repository_connection(state: str) -> dict:
	"""Create the Deploy App once GitHub returned from the install; pushes to its branch deploy from then on."""
	app = DeployConnectionAttempt.complete(state, frappe.session.user)
	return {"name": app.name, "repository": app.repository, "branch": app.branch, "domain": app.domain}


@frappe.whitelist(methods=["GET"])
def get_apps(team: str) -> list[dict]:
	"""The team's deploy apps, newest first. The user sees them with app:view."""
	return frappe.get_list(
		"Deploy App",
		filters={"team": team},
		fields=["name", "repository", "branch", "status", "region", "domain", "virtual_machine", "creation"],
		order_by="creation desc",
	)


@frappe.whitelist(methods=["POST"])
def disable_app(name: str) -> None:
	"""Stop deploying the app on push. A deploy already running finishes, and the VM and domain keep running.
	Connecting the repository again makes the app active."""
	app: DeployApp = frappe.get_doc("Deploy App", name)
	app.check_permission("read")
	if not can(frappe.session.user, app.team, "app:deploy"):
		frappe.throw(_("You can't change the apps of this team."), frappe.PermissionError)
	app.disable()


@frappe.whitelist(methods=["GET"])
def get_app_secrets(name: str) -> list[str]:
	"""The names of the app's secrets. Their values never leave Central except to the app's deploy agent."""
	app: DeployApp = frappe.get_doc("Deploy App", name)
	app.check_permission("read")
	return [secret.key for secret in app.secrets]


@frappe.whitelist(methods=["POST"])
def update_app_secrets(name: str, secrets: dict | None = None, unset: list | None = None) -> list[str]:
	"""Set `secrets` (name to value) and remove the names in `unset`; the container gets them on the next push.
	Returns the app's secret names."""
	app: DeployApp = frappe.get_doc("Deploy App", name)
	app.check_permission("read")
	# Who can deploy the app's code can already read its secrets at runtime, so app:deploy is enough.
	if not can(frappe.session.user, app.team, "app:deploy"):
		frappe.throw(_("You can't change the apps of this team."), frappe.PermissionError)
	app.update_secrets(secrets or {}, unset or [])
	return [secret.key for secret in app.secrets]


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


# Called via callback
def finish_github_sign_in(state: str, code: str | None, installation_id: str | None) -> None:
	"""The GitHub App's callback for a deploy attempt: after the sign-in, or after an install it sent the user to."""
	if not code:
		return frappe.respond_as_web_page(
			_("GitHub sign-in cancelled"),
			_("Start the connection again to deploy this repository."),
			indicator_color="orange",
		)

	next_url = DeployConnectionAttempt.verify(state, code, installation_id, frappe.session.user)
	if next_url:
		# GitHub's install page, its configure page when the App is on the account already, or the
		# installation's settings, where an owner accepts the deploy permissions.
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = next_url
		return

	frappe.respond_as_web_page(
		_("GitHub connected"),
		_("Go back to where you started to finish connecting it."),
		indicator_color="green",
	)


def queue_push_deploys(push: dict, delivery: str | None) -> None:
	"""Queue a deploy of each app the push matches. GitHub's webhook calls this; each delivery is handled once."""
	if not delivery:
		frappe.throw(_("Missing X-GitHub-Delivery header."))
	key = frappe.cache.make_key(f"github-deploy:delivery:{delivery}")
	# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix.
	if not frappe.cache.set(key, 1, nx=True, ex=DELIVERY_TTL_SECONDS):
		return

	for app in get_deploy_apps(push):
		DeployRequest.queue(app, push["after"], delivery)


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

	if request.status in FINISHED_STATES:
		return

	request.release_status = status
	request.release_reported_at = now_datetime()
	request.append_log("release_log", logs)
	# The agent reports on the team's release; no Desk user owns it.
	request.save(ignore_permissions=True)
