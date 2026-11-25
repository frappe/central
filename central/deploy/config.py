import tomllib

import frappe
from frappe import _
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_FILE = "frappe_cloud_deploy.toml"
# What `buildah build .` looks for at the root of the context, in order, when no `-f` is given.
CONTAINERFILE_NAMES = ("Containerfile", "Dockerfile")
# The agent writes the path into an environment file, so it holds only URL path characters.
HEALTH_PATH_PATTERN = r"^(/[A-Za-z0-9._~%/-]*)?$"
DEFAULT_HEALTH_TIMEOUT_SECONDS = 60
MAX_HEALTH_TIMEOUT_SECONDS = 600


class MachineConfig(BaseModel):
	"""`[machine]`: the server plan the VM runs and is billed at, by its title (Starter, Growth, Pro…).
	Without a size, Central Settings' Default Deploy Size."""

	model_config = ConfigDict(extra="forbid", strict=True)

	size: str | None = None


class HealthConfig(BaseModel):
	"""`[health]`: what the new container must answer before traffic moves to it.
	Without a path, any HTTP answer on `/` will do; with one, it must return 2xx."""

	model_config = ConfigDict(extra="forbid", strict=True)

	path: str = Field(default="", pattern=HEALTH_PATH_PATTERN)
	timeout: int = Field(default=DEFAULT_HEALTH_TIMEOUT_SECONDS, gt=0, le=MAX_HEALTH_TIMEOUT_SECONDS)


class DeployConfig(BaseModel):
	"""A `frappe_cloud_deploy.toml`. Each table is added here when deploys start reading it."""

	model_config = ConfigDict(extra="forbid", strict=True)

	machine: MachineConfig = Field(default_factory=MachineConfig)
	health: HealthConfig = Field(default_factory=HealthConfig)


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


def get_machine_size(config: DeployConfig) -> str:
	"""The size the commit's config names, else Central Settings' Default Deploy Size."""
	size = config.machine.size or frappe.db.get_single_value("Central Settings", "deploy_default_size")
	if not size:
		frappe.throw(_("Set a Default Deploy Size in Central Settings."))
	return size
