# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
from cloudtoolkit.pipeline.doctype.pipeline.decorators import flow, task
from cloudtoolkit.pipeline.doctype.pipeline.pipeline_builder import PipelineBuilder
from frappe import _
from frappe.model.naming import append_number_if_name_exists, make_autoname
from frappe.query_builder.functions import IfNull
from frappe.utils import ceil, now_datetime, time_diff_in_seconds
from redis.exceptions import LockError

from central.billing.catalog.subscriptions import begin_resize
from central.deploy.billing import (
	get_plan_size,
	get_shape_includes,
	get_size_plan,
	open_vm_subscription,
	validate_vm_purchase,
)
from central.deploy.config import (
	CONFIG_FILE,
	DEFAULT_HEALTH_TIMEOUT_SECONDS,
	find_containerfile,
	get_deploy_config,
)
from central.deploy.notifications import notify
from central.deploy.virtual_machine import DeployMachine
from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES
from central.integrations import servers
from central.integrations.github import GitHubApp
from central.utils.units import mebibytes_to_gigabytes, millicores_to_vcpus

if TYPE_CHECKING:
	from datetime import datetime

	from cloudtoolkit.pipeline.doctype.pipeline.pipeline import Pipeline

	from central.deploy.doctype.deploy_app.deploy_app import DeployApp
	from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
	from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine

# A newer push replaces a request in these states, unless its build succeeded: the agent then starts the release at
# once, and a release is never interrupted.
SUPERSEDABLE_STATES = ("Queued", "Validating", "Provisioning", "Building")
# Long enough for Atlas to answer one create; another worker skips the app meanwhile.
VM_LOCK_SECONDS = 5 * 60
# The agent reports while it builds; a build that runs longer fails the deploy.
BUILD_TIMEOUT_SECONDS = 60 * 60
# The agent reports every 10 to 20 seconds; silence this long means its VM or the agent died.
BUILD_REPORT_TIMEOUT_SECONDS = 5 * 60
# Longer than the agent takes to start the container, wait out the longest health timeout, and switch traffic.
RELEASE_TIMEOUT_SECONDS = 15 * 60
# The states in which the console's resize reshapes a VM on Atlas.
LIVE_STATES = ("Running", "Paused", "Stopped")
# A log past this keeps its first part and its newest lines, so a runaway build can't fill the row.
MAX_LOG_CHARACTERS = 1024 * 1024
LOG_HEAD_CHARACTERS = 256 * 1024
SKIPPED_LOG_MARKER = "\n... earlier output skipped ...\n"
# The agent's chunks collect in Redis while the deploy runs and are copied to the row once it finishes. Each append
# renews the TTL, which outlasts the build and the release, so a log stays until its deploy finishes.
LOG_FIELDS = ("build_log", "release_log")
LOG_BUFFER_TTL_SECONDS = 2 * (BUILD_TIMEOUT_SECONDS + RELEASE_TIMEOUT_SECONDS)
FINISHED_STATES = ("Succeeded", "Failed", "Superseded")
# What GitHub shows on the commit for each status; a status not listed is pending.
COMMIT_STATES = {"Succeeded": "success", "Failed": "failure", "Superseded": "error"}
COMMIT_DESCRIPTIONS = {
	"Queued": "Waiting to deploy",
	"Validating": "Checking the commit",
	"Provisioning": "Preparing the virtual machine",
	"Building": "Building the image",
	"Releasing": "Releasing the new container",
	"Succeeded": "Live",
	"Failed": "The deploy failed. See its logs in Central.",
	"Superseded": "A newer push replaced this deploy",
}


class DeploySupersededError(frappe.ValidationError):
	"""A newer push replaced this deploy while it ran."""


class DeployBuildError(frappe.ValidationError):
	"""The deploy agent failed the build."""


class DeployReleaseError(frappe.ValidationError):
	"""The new container failed its health check, so the old one keeps serving."""


class DeployTimeoutError(frappe.ValidationError):
	"""A step waited longer than it may."""


class DeployRequest(PipelineBuilder):
	"""One push of one Deploy App."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		build_log: DF.Code | None
		build_reported_at: DF.Datetime | None
		build_status: DF.Literal["", "Running", "Succeeded", "Failed"]
		commit: DF.Data
		cpu_millicores: DF.Int
		delivery: DF.Data | None
		deploy_app: DF.Link
		disk_mib: DF.Int
		error: DF.SmallText | None
		health_path: DF.Data | None
		health_timeout: DF.Int
		memory_mib: DF.Int
		plan: DF.Link | None
		release_log: DF.Code | None
		release_reported_at: DF.Datetime | None
		release_status: DF.Literal["", "Releasing", "Live", "Failed"]
		status: DF.Literal[
			"Queued",
			"Validating",
			"Provisioning",
			"Building",
			"Releasing",
			"Succeeded",
			"Failed",
			"Superseded",
		]
		team: DF.Link
	# end: auto-generated types

	@staticmethod
	def queue(deploy_app: str, commit: str, delivery: str | None = None) -> DeployRequest:
		"""Queue `commit` for the app, superseding the requests a newer push replaces."""
		# The app's row lock makes two pushes to one app queue one after the other.
		team = frappe.db.get_value("Deploy App", deploy_app, "team", for_update=True)
		request_table = frappe.qb.DocType("Deploy Request")
		# A locking read waits for report_build and sees its result, so the agent and Central agree whether a deploy
		# releases.
		supersedable_requests = (
			frappe.qb.from_(request_table)
			.select(request_table.name)
			.where(request_table.deploy_app == deploy_app)
			.where(request_table.status.isin(SUPERSEDABLE_STATES))
			.where(IfNull(request_table.build_status, "") != "Succeeded")
			.for_update()
			.run(pluck=True)
		)
		for request in supersedable_requests:
			request_doc: DeployRequest = frappe.get_doc("Deploy Request", request, for_update=True)
			request_doc.status = "Superseded"
			# Central supersedes the team's older deploy; no Desk user owns it.
			request_doc.save(ignore_permissions=True)

		# Central queues the deploy for the team's app; no Desk user owns it.
		return frappe.get_doc(
			{
				"doctype": "Deploy Request",
				"deploy_app": deploy_app,
				"team": team,
				"commit": commit,
				"delivery": delivery,
			}
		).insert(ignore_permissions=True)

	def autoname(self):
		"""`<app>-<6 characters of the commit>`; a commit deployed again gets -1, -2 and so on."""
		self.name = append_number_if_name_exists(self.doctype, f"{self.deploy_app}-{self.commit[:6]}")

	def after_insert(self):
		"""We know which app we are deploying therefore let's start the flow form here."""
		self.start_deploy.run_as_pipeline()

	@flow
	def start_deploy(self):
		"""Size the VM from the commit's config, bring the app's VM to that size, then build the commit on it."""
		self.ensure_dockerfile()
		self.check_machine_specs()
		self.converge_virtual_machine()
		self.wait_for_build()
		self.wait_for_release()
		self.create_domain_mapping()

	@task
	def ensure_dockerfile(self) -> str:
		"""Fail early when the commit has no Containerfile or Dockerfile Buildah would find, since the build agent can't
		generate one yet. Returns its exact name."""
		self.set_status("Validating")
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		installation_id = app.get_installation_id()
		# One listing of the root, so case and the file's type are read from GitHub, not guessed.
		root = GitHubApp().list_root(installation_id, app.repository_id, app.repository, self.commit)
		return find_containerfile(root)

	@task
	def check_machine_specs(self) -> None:
		"""Take the VM's plan from `[machine] size` in the commit's config, else Central Settings' default size."""
		self.set_status("Provisioning")
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		if not app.region:
			frappe.throw(_("Choose a region for {0} first.").format(app.repository))
		installation_id = app.get_installation_id()
		config = GitHubApp().get_file(
			installation_id, app.repository_id, app.repository, CONFIG_FILE, self.commit
		)
		deploy_config = get_deploy_config(config)
		self.plan = get_size_plan(app.team, app.region, deploy_config.get_machine_size(), app.virtual_machine)
		self.health_path = deploy_config.health.path
		self.health_timeout = deploy_config.health.timeout
		# Central records the size the team's commit asks for; no Desk user owns the deploy.
		self.save(ignore_permissions=True)

	@task
	def converge_virtual_machine(self) -> None:
		"""Bring the app's VM to this deploy's plan and wait until it runs. Every wait runs this again from the top,
		so each pass compares the plan with what Atlas reports and takes only the next step."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		server: VirtualMachine = frappe.get_doc("Virtual Machine", self.get_virtual_machine(app))
		if self.is_resizing(server.name):
			self.wait(_("Resizing {0}.").format(server.name), for_=900)
			return

		machine = DeployMachine(app)
		vm = machine.get(server.atlas_vm_id)
		if vm.get("current_state") == "migrating":
			self.wait(_("Atlas is moving {0} to a host that fits it.").format(server.name), for_=900)
			return

		status = servers.observe_server(server)
		specs, plan_specs = machine.get_specs(vm), get_plan_size(self.plan)
		disk_gigabytes = ceil(mebibytes_to_gigabytes(max(plan_specs["disk_mib"], specs["disk_mib"])))
		subscription = frappe.db.get_value("Subscription", {"server_id": server.name}, "name")
		# This resize is a no-op if there are no plan changes.
		if (
			status in LIVE_STATES
			and begin_resize(subscription, plan=self.plan, disk_gigabytes=disk_gigabytes)["queued"]
		):
			self.wait(_("Resizing {0}.").format(server.name), for_=900)
			return

		if status == "Stopped":
			machine.start(server.atlas_vm_id)
		if status != "Running":
			self.wait(_("Virtual Machine {0} is not ready yet.").format(server.name), for_=500)
			return

		if specs["disk_mib"] > plan_specs["disk_mib"] and specs["disk_mib"] != self.disk_mib:
			self.append_log("build_log", _("Preserving disk size as shrink is not allowed"))

		self.update(specs)
		self.save(ignore_permissions=True)

	def get_virtual_machine(self, app: DeployApp) -> str:
		"""The app's VM, found or created. One deploy per app looks at a time."""
		try:
			# A Redis lock, not a row lock: no transaction stays open while Atlas answers.
			with frappe.cache.lock(
				f"deploy-app-vm:{self.deploy_app}", timeout=VM_LOCK_SECONDS, blocking_timeout=0
			):
				return self.find_or_create_virtual_machine(app)
		except LockError:
			self.wait(
				_("Another deploy of {0} is creating its virtual machine.").format(self.deploy_app), for_=300
			)

	def is_resizing(self, server: str) -> bool:
		"""Whether the resize this step queued is still running. A resize that failed fails the deploy with its error."""
		action = frappe.db.get_value(
			"Resource Action",
			{"server": server, "action": "resize", "creation": (">=", self.step_started)},
			"name",
			order_by="creation desc",
		)
		if not action:
			return False

		action: ResourceAction = frappe.get_doc("Resource Action", action)
		if action.status in PENDING_STATES:
			return True
		if action.status != "Succeeded":
			error = action.customer_status()["error"]
			frappe.throw(error["message"] if error else _("Resizing {0} failed.").format(server))
		return False

	@task
	def wait_for_build(self):
		"""The deploy agent on the VM gets the build and reports on it; this only waits for its result."""
		self.set_status("Building")
		if self.build_status == "Failed":
			frappe.throw(_("The build failed. See its log."), DeployBuildError)
		if self.build_status == "Succeeded":
			return
		# A report arriving after this gets `cancel`, since the request is no longer Building.
		if self.is_silent(self.build_reported_at):
			frappe.throw(_("The deploy agent stopped reporting on the build."), DeployTimeoutError)
		self.wait(_("The build has not finished."), for_=BUILD_TIMEOUT_SECONDS)

	@task
	def wait_for_release(self):
		"""The agent starts the new container next to the old one and moves traffic to it once it passes its health
		check; this only waits for its result."""
		self.set_status("Releasing")
		if self.release_status == "Failed":
			frappe.throw(
				_("The new container failed its health check. The old one keeps serving."), DeployReleaseError
			)
		if self.release_status == "Live":
			return
		# Also fails a release the agent never started, since it reports Releasing only once it runs.
		if self.is_silent(self.release_reported_at):
			frappe.throw(_("The deploy agent stopped reporting on the release."), DeployTimeoutError)
		self.wait(_("The release has not finished."), for_=RELEASE_TIMEOUT_SECONDS)

	@task
	def create_domain_mapping(self):
		"""Route the app's domain to its VM on the first deploy. Later deploys keep the same URL and the same VM,
		so they find the route and change nothing."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		if not app.domain:
			frappe.throw(_("{0} has no domain. Connect the repository again.").format(app.repository))
		if frappe.db.exists("Site Domain", app.domain):
			return

		# Site Domain checks the name, sends it to the regional proxy, and retries until the proxy takes it.
		frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": app.domain,
				"server": app.virtual_machine,
				"team": app.team,
				"region": app.region,
			}
		).insert(ignore_permissions=True)

	def on_update(self):
		if self.has_value_changed("status"):
			# After commit, so the job reads this status; a GitHub outage never fails the deploy.
			frappe.enqueue_doc(
				self.doctype, self.name, "update_github_commit_status", enqueue_after_commit=True
			)

		if self.has_value_changed("status") and self.status == "Succeeded":
			frappe.enqueue_doc(
				self.doctype, self.name, "update_github_deployment_status", enqueue_after_commit=True
			)

	def update_github_deployment_status(self) -> None:
		"""Record the live deploy as a GitHub deployment, which shows the app's domain on the repository page."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		if not app.domain:
			return
		GitHubApp().create_deployment(
			app.get_installation_id(),
			app.repository_id,
			app.repository,
			self.commit,
			environment_url=f"https://{app.domain}",
		)

	def update_github_commit_status(self) -> None:
		"""Show this deploy's current status on its commit in GitHub."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		installation_id = app.get_installation_id()
		GitHubApp().set_commit_status(
			installation_id,
			app.repository_id,
			app.repository,
			self.commit,
			state=COMMIT_STATES.get(self.status, "pending"),
			description=COMMIT_DESCRIPTIONS[self.status],
			target_url=f"https://{app.domain}" if self.status == "Succeeded" and app.domain else None,
		)

	def validate(self):
		if self.has_value_changed("status") and self.status in FINISHED_STATES:
			self.flush_logs()

	def append_log(self, field: str, chunk: str) -> None:
		"""Add the lines the agent sent since its last report to the Redis log of `field`."""
		if chunk:
			key = get_log_key(self.name, field)
			frappe.cache.rpush(key, chunk)
			frappe.cache.expire_key(key, LOG_BUFFER_TTL_SECONDS)

	def flush_logs(self) -> None:
		"""Replace the saved logs with the Redis ones; the save that finishes the deploy writes them."""
		for field in LOG_FIELDS:
			if chunks := frappe.cache.lrange(get_log_key(self.name, field), 0, -1):
				self.set(field, cap_log(get_text(chunks)))

	def get_log(self, field: str) -> str:
		"""While the deploy runs, the buffer in Redis, or the saved log when Redis has none; after, the saved log."""
		if self.status not in FINISHED_STATES:
			chunks = frappe.cache.lrange(get_log_key(self.name, field), 0, -1)
			if chunks:
				return cap_log(get_text(chunks))
		return self.get(field) or ""

	def is_silent(self, last_reported: datetime | None) -> bool:
		"""No report since the last one, or since the current step started, for too long."""
		last_heard = last_reported or self.step_started
		return time_diff_in_seconds(now_datetime(), last_heard) > BUILD_REPORT_TIMEOUT_SECONDS

	def find_or_create_virtual_machine(self, app: DeployApp) -> str:
		"""Link the app's VM: the one Atlas already has for it, or a new one at this deploy's plan.
		The caller holds the app's lock, so Atlas is never asked for a second VM."""
		if app.virtual_machine:
			return app.virtual_machine
		if not app.region:
			frappe.throw(_("Choose a region for {0} first.").format(app.repository))

		machine = DeployMachine(app)
		# Atlas may hold a VM whose create reply was lost; that one is reused, not created again.
		found = machine.find()
		if len(found) > 1:
			frappe.throw(
				_("Atlas has more than one VM for {0}. An operator must remove the extra one.").format(
					app.name
				)
			)
		if found:
			# The size a lost create asked for is unknown, so the VM is billed at the size Atlas reports.
			# The converge step then resizes it to this deploy's plan.
			atlas_vm_id, image_id = found[0]["id"], found[0].get("image_id")
			specs = machine.get_specs(machine.get(atlas_vm_id))
			server = self.record_virtual_machine(app, atlas_vm_id, image_id, None, specs)
			open_vm_subscription(server.name, app.team, app.region, includes=get_shape_includes(specs))
		else:
			image_id = machine.get_newest_image_id()
			if not image_id:
				frappe.throw(_("Region {0} has no deploy image yet.").format(app.region))
			rate = validate_vm_purchase(app.team, app.region, self.plan)
			specs = get_plan_size(self.plan)
			atlas_vm_id = machine.create(image_id, specs)
			server = self.record_virtual_machine(app, atlas_vm_id, image_id, self.plan, specs)
			open_vm_subscription(server.name, app.team, app.region, plan=self.plan, rate=rate)

		app.virtual_machine = server.name
		# Central links the server it created for the team's app; no Desk user owns it.
		app.save(ignore_permissions=True)
		return server.name

	def record_virtual_machine(
		self, app: DeployApp, atlas_vm_id: str, image_id: str | None, plan: str | None, specs: dict[str, int]
	) -> VirtualMachine:
		"""The Virtual Machine row Central shows and observes for the app's VM. Each Atlas VM gets its own row,
		named like any other server, so a VM that replaces a terminated one does not reuse the old row."""
		if name := frappe.db.get_value("Virtual Machine", {"region": app.region, "atlas_vm_id": atlas_vm_id}):
			return frappe.get_doc("Virtual Machine", name)

		# This is required since otherwise it's borrowed from resource action (which we don't use here)
		# Or this comes from deploy app hash, however reconnecting a disabled app would then point to a dead vm
		name = f"server-{make_autoname('hash')}"

		server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": name,
				"title": app.repository,
				"team": app.team,
				"region": app.region,
				"status": "Provisioning",
				"atlas_vm_id": atlas_vm_id,
				"atlas_image_id": image_id,
				"plan": plan,
				"vcpus": millicores_to_vcpus(specs["cpu_millicores"]),
				"memory_megabytes": specs["memory_mib"],
				"disk_gigabytes": mebibytes_to_gigabytes(specs["disk_mib"]),
				"is_firewall_enabled": 1,
			}
		)
		# Central records the server it created for the team's app; no Desk user owns it.
		return server.insert(ignore_permissions=True)

	def get_build_payload(self) -> dict:
		"""What the agent needs to fetch and build the commit; the token reads only this repository."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		installation_id = app.get_installation_id()
		token = GitHubApp().create_installation_token(installation_id, app.repository_id)["token"]
		secrets = {secret.key: secret.get_password("value") for secret in app.secrets}
		return {
			"deploy_request": self.name,
			"repository": app.repository,
			"commit": self.commit,
			"token": token,
			"health_path": self.health_path or "",
			# Requests queued before the commit's config was read have none.
			"health_timeout": self.health_timeout or DEFAULT_HEALTH_TIMEOUT_SECONDS,
			"secrets": secrets,
		}

	def on_pipeline_success(self, pipeline: Pipeline) -> None:
		self.set_status("Succeeded")

	def on_pipeline_failure(self, pipeline: Pipeline) -> None:
		self.reload()
		if self.status == "Superseded":
			return

		traceback = (pipeline.pipeline_traceback or pipeline.traceback or "").strip()
		self.error = traceback.splitlines()[-1] if traceback else _("The deploy failed.")
		self.set_status("Failed")
		notify(self.deploy_app, "deploy_failed", self.error)

	def set_status(self, status: str) -> None:
		"""Save `status`, unless a newer push superseded this deploy meanwhile, which stops its pipeline."""
		error = self.error
		# The webhook may have superseded this row since the pipeline loaded it.
		self.reload()
		if self.status == "Superseded":
			frappe.throw(_("A newer push superseded this deploy."), DeploySupersededError)
		if self.status == status and self.error == error:
			return

		self.status = status
		self.error = error
		# Central moves the team's deploy through its steps; no Desk user owns it.
		self.save(ignore_permissions=True)


def cap_log(log: str) -> str:
	"""`log`, or its start and its newest lines once it is longer than MAX_LOG_CHARACTERS."""
	if len(log) <= MAX_LOG_CHARACTERS:
		return log

	tail = log[LOG_HEAD_CHARACTERS:][-(MAX_LOG_CHARACTERS - LOG_HEAD_CHARACTERS - len(SKIPPED_LOG_MARKER)) :]
	return log[:LOG_HEAD_CHARACTERS] + SKIPPED_LOG_MARKER + tail


def get_log_key(deploy_request: str, field: str) -> str:
	return f"deploy-log:{deploy_request}:{field}"


def get_text(chunks: list[bytes]) -> str:
	return "".join(chunk.decode() for chunk in chunks)


def on_doctype_update() -> None:
	frappe.db.add_index("Deploy Request", ["deploy_app", "status"])
