import tomllib

import frappe
from frappe import _
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_FILE = "frappe_cloud_deploy.toml"
# What `buildah build .` looks for at the root of the context, in order, when no `-f` is given.
CONTAINERFILE_NAMES = ("Containerfile", "Dockerfile")
# A build needs room, so a deploy VM starts at Growth unless the config names another size.
DEFAULT_SIZE = "Growth"


class MachineConfig(BaseModel):
	"""`[machine]`: the server plan the VM runs and is billed at, by its title (Starter, Growth, Pro…)."""

	model_config = ConfigDict(extra="forbid", strict=True)

	size: str = DEFAULT_SIZE


class DeployConfig(BaseModel):
	"""A `frappe_cloud_deploy.toml`. Each table is added here when deploys start reading it."""

	model_config = ConfigDict(extra="forbid", strict=True)

	machine: MachineConfig = Field(default_factory=MachineConfig)


def get_deploy_config(config: str | None) -> DeployConfig:
	"""The commit's `frappe_cloud_deploy.toml`, or the defaults when it has none."""
	if config is None:
		return DeployConfig()
	try:
		return DeployConfig.model_validate(tomllib.loads(config))
	except tomllib.TOMLDecodeError as error:
		frappe.throw(_("{0} is not valid TOML: {1}").format(CONFIG_FILE, str(error)))
	except ValidationError as error:
		problems = "; ".join(
			f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
			for problem in error.errors()
		)
		frappe.throw(_("{0} is not valid: {1}").format(CONFIG_FILE, problems))


def find_containerfile(root: list[dict]) -> str:
	"""The file `buildah build .` would use, from the root listing of the repository."""
	for name in CONTAINERFILE_NAMES:
		entry = next((entry for entry in root if entry["name"] == name), None)
		if entry and entry.get("type") != "file":
			frappe.throw(_("{0} must be a regular file, not a {1}.").format(name, entry.get("type")))
		if entry:
			return name

	# A name that differs only in case: the user meant it, so name the fix.
	wanted = {name.lower(): name for name in CONTAINERFILE_NAMES}
	if near := next((entry["name"] for entry in root if entry["name"].lower() in wanted), None):
		frappe.throw(
			_("Rename {0} to {1}. Buildah only finds Containerfile or Dockerfile.").format(
				near, wanted[near.lower()]
			)
		)
	frappe.throw(_("Add a Dockerfile at the root of the repository and push again."))
