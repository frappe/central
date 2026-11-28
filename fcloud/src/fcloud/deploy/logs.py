import time

from rich.text import Text

from fcloud.central import Central
from fcloud.deploy.app import get_deploy_request
from fcloud.output import console, get_status_text

POLL_SECONDS = 3
FINISHED = ("Succeeded", "Failed", "Superseded")
LOG_FIELDS = (("build_log", "build"), ("release_log", "release"))


class DeployLog:
	"""Prints a deploy request's status, task statuses, and logs, showing only what changed since the last poll."""

	def __init__(self, central: Central, name: str):
		self.central = central
		self.name = name
		self.status: str | None = None
		self.task_statuses: dict[int, str] = {}
		self.logs = {field: "" for field, _ in LOG_FIELDS}

	def show(self, follow: bool = False) -> dict:
		"""Print the deploy once, or poll until it finishes. Return its last state."""
		while True:
			deploy = get_deploy_request(self.central, self.name)
			self.print_changes(deploy)
			if not follow or deploy["status"] in FINISHED:
				return deploy
			time.sleep(POLL_SECONDS)

	def print_changes(self, deploy: dict) -> None:
		if deploy["status"] != self.status:
			heading = Text(f"==> {deploy['name']} ({deploy['commit'][:8]}): ", style="bold")
			console.print(heading + get_status_text(deploy["status"]))
			self.status = deploy["status"]

		for index, task in enumerate(deploy["tasks"]):
			if self.task_statuses.get(index) != task["status"]:
				console.print(
					Text("  [") + get_status_text(task["status"]) + Text(f"] {task['method_title']}")
				)
				self.task_statuses[index] = task["status"]

		for field, label in LOG_FIELDS:
			log, previous = deploy[field] or "", self.logs[field]
			# Central cuts a log over its size limit in the middle, so the old prefix stops matching.
			new = log[len(previous) :] if log.startswith(previous) else log
			for line in new.splitlines():
				console.print(Text.assemble((f"  {label} | ", "dim"), line))
			self.logs[field] = log
