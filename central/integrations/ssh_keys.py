from __future__ import annotations

import frappe
from frappe import _

from central.errors import AtlasConnectionError, AtlasRejected, AtlasRequestUncertain, AtlasResourceGone
from central.integrations.atlas import AtlasClient


def sync_team_ssh_key(name: str) -> None:
	"""Replace the complete key set on every live VM that selected this key."""
	key = frappe.get_doc("Team SSH Key", name)
	links = frappe.get_all("Server SSH Key", filters={"team_ssh_key": name}, fields=["parent"])
	errors: list[str] = []
	for link in links:
		server = frappe.db.get_value(
			"Virtual Machine", link.parent, ["name", "team", "region", "atlas_vm_id", "status"], as_dict=True
		)
		if not server or server.team != key.team or not server.atlas_vm_id or server.status == "Terminated":
			continue
		try:
			_sync_server(server)
		except (AtlasConnectionError, AtlasRejected, AtlasRequestUncertain, AtlasResourceGone, ValueError):
			frappe.log_error(title=f"SSH key sync failed for {server.name}", message=frappe.get_traceback())
			errors.append(server.name)
	key.db_set(
		"last_sync_error",
		_("Could not update {0}. Retry synchronization.").format(", ".join(errors)) if errors else None,
	)


def _sync_server(server) -> None:
	with frappe.cache.lock(f"server-ssh-keys:{server.name}", timeout=60):
		_replace_server_keys(server)


def _replace_server_keys(server) -> None:
	links = frappe.get_all(
		"Server SSH Key", filters={"parent": server.name}, fields=["team_ssh_key"], order_by="idx asc"
	)
	names = [link.team_ssh_key for link in links]
	keys = frappe.get_all(
		"Team SSH Key", filters={"team": server.team, "name": ["in", names]}, fields=["name", "public_key"]
	)
	public_keys = {key.name: key.public_key for key in keys}
	if len(public_keys) != len(names):
		raise ValueError("A selected Team SSH Key is missing")
	client = AtlasClient(
		frappe.get_doc("Region", server.region), frappe.get_cached_value("Team", server.team, "tenant_id")
	)
	client.replace_vm_ssh_keys(server.atlas_vm_id, [public_keys[name] for name in names])
