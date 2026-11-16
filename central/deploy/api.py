import json

import frappe
from frappe import _

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.deploy.doctype.deploy_request.deploy_request import DeployRequest
from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
	GitHubDeployAppInstallation,
)
from central.deploy.github import GitHubDeployApp

DELIVERY_TTL_SECONDS = 24 * 60 * 60
BRANCH_REF_PREFIX = "refs/heads/"


# nosemgrep: guest-whitelisted-method -- the state binds the callback to the user who started it.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def oauth_callback(
	state: str | None = None, code: str | None = None, installation_id: str | None = None, **kwargs
) -> None:
	"""GitHub returns here after an install. An install started on github.com has no state to link."""
	if not (state and code and installation_id):
		return frappe.respond_as_web_page(
			_("Nothing to connect"),
			_("Start the connection from Frappe Cloud, then install the GitHub App from the link it gives."),
			indicator_color="orange",
		)

	GitHubDeployAppInstallation.verify(state, code, installation_id, frappe.session.user)
	frappe.respond_as_web_page(
		_("GitHub App installed"),
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
