import tomllib

import frappe
from frappe import _

CONFIG_FILE = "frappe_cloud_deploy.toml"
# What `buildah build .` looks for at the root of the context, in order, when no `-f` is given.
CONTAINERFILE_NAMES = ("Containerfile", "Dockerfile")
# Inclusive bounds for each `[machine]` key, in Atlas units. Will make this configurabale in team later.
MACHINE_LIMITS = {
	"cpu_millicores": (100, 32000),
	"memory_mib": (512, 128 * 1024),
	"disk_mib": (10 * 1024, 1024 * 1024),
}


def get_machine_specs(config: str | None) -> dict[str, int]:
	"""The `[machine]` keys of a `frappe_cloud_deploy.toml`, checked against `MACHINE_LIMITS`."""
	if config is None:
		return {}
	try:
		machine = tomllib.loads(config).get("machine", {})
	except tomllib.TOMLDecodeError as error:
		frappe.throw(_("{0} is not valid TOML: {1}").format(CONFIG_FILE, str(error)))

	if not isinstance(machine, dict):
		frappe.throw(_("[machine] in {0} must be a table.").format(CONFIG_FILE))
	if unknown := set(machine) - set(MACHINE_LIMITS):
		frappe.throw(_("Unknown keys in [machine]: {0}").format(", ".join(sorted(unknown))))
	for key, value in machine.items():
		low, high = MACHINE_LIMITS[key]
		if type(value) is not int or not low <= value <= high:
			frappe.throw(_("machine.{0} must be a whole number from {1} to {2}.").format(key, low, high))
	return machine


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
