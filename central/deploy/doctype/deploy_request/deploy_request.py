# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
from cloudtoolkit.pipeline.doctype.pipeline.decorators import flow, task
from cloudtoolkit.pipeline.doctype.pipeline.pipeline_builder import PipelineBuilder
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds
from redis.exceptions import LockError

from central.deploy.agent import DeployAgent, DeployAgentError
from central.deploy.config import CONFIG_FILE, MACHINE_LIMITS, get_machine_specs
from central.deploy.github import GitHubDeployApp
from central.deploy.virtual_machine import DeployMachine
from central.integrations import servers
from central.utils.units import mebibytes_to_gigabytes, millicores_to_vcpus

if TYPE_CHECKING:
	from cloudtoolkit.pipeline.doctype.pipeline.pipeline import Pipeline

	from central.deploy.doctype.deploy_app.deploy_app import DeployApp
	from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine

# A newer push replaces a request in these states. A release is never interrupted.
SUPERSEDABLE_STATES = ("Queued", "Provisioning", "Building")
# Long enough for Atlas to answer one create; another worker skips the app meanwhile.
VM_LOCK_SECONDS = 5 * 60


class DeploySupersededError(frappe.ValidationError):
	"""A newer push replaced this deploy while it ran."""


class DeployRequest(PipelineBuilder):
	"""One push of one Deploy App."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_build_id: DF.Data | None
		commit: DF.Data
		cpu_millicores: DF.Int
		delivery: DF.Data | None
		deploy_app: DF.Link
		disk_mib: DF.Int
		error: DF.SmallText | None
		memory_mib: DF.Int
		status: DF.Literal[
			"Queued", "Provisioning", "Building", "Releasing", "Succeeded", "Failed", "Superseded"
		]
		team: DF.Link
	# end: auto-generated types

	@staticmethod
	def queue(deploy_app: str, commit: str, delivery: str | None = None) -> DeployRequest:
		"""Queue `commit` for the app, superseding the requests a newer push replaces."""
		# The app's row lock makes two pushes to one app queue one after the other.
		team = frappe.db.get_value("Deploy App", deploy_app, "team", for_update=True)
		for name in frappe.get_all(
			"Deploy Request",
			filters={"deploy_app": deploy_app, "status": ["in", SUPERSEDABLE_STATES]},
			pluck="name",
		):
			request = frappe.get_doc("Deploy Request", name, for_update=True)
			request.status = "Superseded"
			# Central supersedes the team's older deploy; no Desk user owns it.
			request.save(ignore_permissions=True)

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

	def after_insert(self):
		"""We know which app we are deploying therefore let's start the flow form here."""
		self.start_deploy.run_as_pipeline()

	@flow
	def start_deploy(self):
		"""Size the VM from the commit's config, get or create it, then build the commit on it."""
		self.check_machine_specs()
		machine = self.get_virtual_machine()
		if not machine["is_new"]:
			self.resize_virtual_machine(machine["name"])
		self.wait_for_virtual_machine(machine["name"])
		self.ping_deploy_agent(machine["name"])
		self.enqueue_deploy_on_agent(machine["name"])

	@task
	def check_machine_specs(self) -> None:
		"""Take the VM size from `[machine]` in the commit's config; keys it leaves out keep the defaults."""
		self.set_status("Provisioning")
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		installation_id = frappe.db.get_value(
			"GitHub Deploy App Installation", app.installation, "installation_id"
		)
		config = GitHubDeployApp().get_file(
			installation_id, app.repository_id, app.repository, CONFIG_FILE, self.commit
		)
		if specs := get_machine_specs(config):
			self.update(specs)
			# Central records the size the team's commit asks for; no Desk user owns the deploy.
			self.save(ignore_permissions=True)

	@task
	def get_virtual_machine(self) -> dict:
		"""The app's VM, and whether this deploy created it. One deploy per app looks at a time."""
		try:
			# A Redis lock, not a row lock: no transaction stays open while Atlas answers.
			with frappe.cache.lock(
				f"deploy-app-vm:{self.deploy_app}", timeout=VM_LOCK_SECONDS, blocking_timeout=0
			):
				return self.find_or_create_virtual_machine()
		except LockError:
			self.wait(
				_("Another deploy of {0} is creating its virtual machine.").format(self.deploy_app), for_=300
			)

	@task
	def resize_virtual_machine(self, name: str) -> None:
		"""Bring a reused VM to this deploy's specs and start it. Atlas resizes only a stopped VM."""
		atlas_vm_id = frappe.db.get_value("Virtual Machine", name, "atlas_vm_id")
		machine = DeployMachine(frappe.get_doc("Deploy App", self.deploy_app))
		vm = machine.get(atlas_vm_id)
		state, current = vm.get("current_state"), machine.get_specs(vm)

		if current == self.specs:
			# No resize required
			if state == "stopped":
				machine.start(atlas_vm_id)
			elif state == "migrating":
				self.wait(_("Atlas is moving {0} to a host that fits it.").format(name), for_=900)
			return

		if self.disk_mib < (current["disk_mib"] or 0):
			frappe.throw(
				_("The disk can't shrink from {0} MiB to {1} MiB.").format(current["disk_mib"], self.disk_mib)
			)
		if state == "running":
			machine.stop(atlas_vm_id)
		elif state == "stopped":
			machine.resize(atlas_vm_id, self.specs)
		self.wait(_("Resizing {0}.").format(name), for_=900)

	@task
	def wait_for_virtual_machine(self, name: str) -> None:
		"""Wait until the VM runs and has the mesh address Central reaches its agent on."""
		server = frappe.get_doc("Virtual Machine", name)
		if servers.observe_server(server) != "Running" or not frappe.db.get_value(
			"Virtual Machine", name, "ipv6_address"
		):
			self.wait(_("Virtual Machine {0} is not ready yet.").format(name), for_=500)

	@task
	def ping_deploy_agent(self, virtual_machine: str):
		try:
			self.get_agent(virtual_machine).get_health()
		except DeployAgentError:
			self.wait(_("The deploy agent on {0} is not answering yet.").format(virtual_machine), for_=300)

	@task
	def enqueue_deploy_on_agent(self, virtual_machine: str):
		"""Start the build once, then defer until the agent reports it finished."""
		self.set_status("Building")
		agent = self.get_agent(virtual_machine)
		if not self.agent_build_id:
			self.agent_build_id = agent.start_build(self.get_build_payload())["build_id"]
			# Central records the team's build; no Desk user owns it.
			self.save(ignore_permissions=True)

		build = agent.get_build(self.agent_build_id)
		if build["status"] == "failed":
			frappe.throw(build.get("error") or _("The build failed."), DeployAgentError)
		if build["status"] != "succeeded":
			self.defer_current_task(_("Build {0} is still running.").format(self.agent_build_id))

	@property
	def specs(self) -> dict[str, int]:
		return {key: self.get(key) for key in MACHINE_LIMITS}

	def find_or_create_virtual_machine(self) -> dict:
		"""Link the app's VM: the one Atlas already has for it, or a new one at this deploy's specs.
		The caller holds the app's lock, so Atlas is never asked for a second VM."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		if app.virtual_machine:
			return {"name": app.virtual_machine, "is_new": False}
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
			atlas_vm_id, image_id = found[0]["id"], found[0].get("image_id")
		else:
			image_id = machine.get_newest_image_id()
			if not image_id:
				frappe.throw(_("Region {0} has no deploy image yet.").format(app.region))
			atlas_vm_id = machine.create(image_id, self.specs)

		server = self.record_virtual_machine(app, atlas_vm_id, image_id)
		app.virtual_machine = server.name
		# Central links the server it created for the team's app; no Desk user owns it.
		app.save(ignore_permissions=True)
		return {"name": server.name, "is_new": not found}

	def record_virtual_machine(
		self, app: DeployApp, atlas_vm_id: str, image_id: str | None
	) -> VirtualMachine:
		"""The Virtual Machine row Central shows and observes for the app's VM."""
		name = f"server-deploy-{app.name}"
		if frappe.db.exists("Virtual Machine", name):
			return frappe.get_doc("Virtual Machine", name)

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
				"vcpus": millicores_to_vcpus(self.cpu_millicores),
				"memory_megabytes": self.memory_mib,
				"disk_gigabytes": mebibytes_to_gigabytes(self.disk_mib),
				"is_firewall_enabled": 1,
			}
		)
		# Central records the server it created for the team's app; no Desk user owns it.
		return server.insert(ignore_permissions=True)

	def get_agent(self, virtual_machine: str) -> DeployAgent:
		return DeployAgent(frappe.get_doc("Virtual Machine", virtual_machine))

	def get_build_payload(self) -> dict:
		"""What the agent needs to fetch and build the commit; the token reads only this repository."""
		app: DeployApp = frappe.get_doc("Deploy App", self.deploy_app)
		installation_id = frappe.db.get_value(
			"GitHub Deploy App Installation", app.installation, "installation_id"
		)
		token = GitHubDeployApp().create_installation_token(installation_id, app.repository_id)["token"]
		return {"repository": app.repository, "commit": self.commit, "token": token}

	def wait(self, message: str, for_: int) -> None:
		"""Try this step again later, or fail the deploy once this step has waited `for_` seconds."""
		task = self.flags.current_pipeline_task
		started = frappe.db.get_value("Pipeline Task", task, "creation") if task else self.creation
		if time_diff_in_seconds(now_datetime(), started) > for_:
			frappe.throw(message, DeployAgentError)
		self.defer_current_task(message)

	def on_pipeline_success(self, pipeline: Pipeline) -> None:
		self.set_status("Succeeded")

	def on_pipeline_failure(self, pipeline: Pipeline) -> None:
		self.reload()
		if self.status == "Superseded":
			self.cancel_build()
			return

		traceback = (pipeline.pipeline_traceback or pipeline.traceback or "").strip()
		self.error = traceback.splitlines()[-1] if traceback else _("The deploy failed.")
		self.set_status("Failed")

	def cancel_build(self) -> None:
		"""Stop the build a newer push replaced, so it doesn't hold the VM's memory."""
		virtual_machine = frappe.db.get_value("Deploy App", self.deploy_app, "virtual_machine")
		if not (self.agent_build_id and virtual_machine):
			return
		try:
			self.get_agent(virtual_machine).cancel_build(self.agent_build_id)
		except DeployAgentError:
			# The newer deploy builds on the same VM anyway; a stuck build shows in its logs.
			frappe.log_error(
				"Could not cancel a superseded build",
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

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


def on_doctype_update() -> None:
	frappe.db.add_index("Deploy Request", ["deploy_app", "status"])
