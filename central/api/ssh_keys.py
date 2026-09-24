from __future__ import annotations

import frappe
from frappe import _

from central.iam import can


def require_access(team: str, capability: str) -> None:
	if not can(frappe.session.user, team, capability):
		frappe.throw(_("You cannot manage SSH keys for this Team."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def list_team_ssh_keys(team: str) -> list[dict]:
	"""Return the public keys that this Team can select for servers."""
	require_access(team, "server:view")
	keys = frappe.get_list(
		"Team SSH Key",
		filters={"team": team},
		fields=["name", "title", "public_key", "fingerprint", "last_sync_error"],
		order_by="title asc",
		limit_page_length=0,
	)
	if not keys:
		return []
	links = frappe.get_all(
		"Server SSH Key",
		filters={"team_ssh_key": ["in", [key.name for key in keys]]},
		fields=["team_ssh_key", "parent"],
	)
	for key in keys:
		key["server_count"] = len({link.parent for link in links if link.team_ssh_key == key.name})
	return keys


@frappe.whitelist(methods=["POST"])
def create_team_ssh_key(team: str, title: str, public_key: str) -> dict:
	"""Create one public key for a Team."""
	require_access(team, "server:ssh-key")
	key = frappe.get_doc(
		{"doctype": "Team SSH Key", "team": team, "title": title, "public_key": public_key}
	).insert()
	return {
		"name": key.name,
		"title": key.title,
		"public_key": key.public_key,
		"fingerprint": key.fingerprint,
		"server_count": 0,
	}


@frappe.whitelist(methods=["POST"])
def rotate_team_ssh_key(team: str, name: str, public_key: str) -> dict:
	"""Save a new public key and queue replacement on selected servers."""
	require_access(team, "server:ssh-key")
	key = frappe.get_doc("Team SSH Key", name)
	if key.team != team:
		frappe.throw(_("This SSH key does not belong to the Team."), frappe.PermissionError)
	if public_key.strip() == key.public_key:
		frappe.throw(_("The replacement SSH key must be different."))
	key.public_key = public_key
	key.save()
	return {"name": key.name, "fingerprint": key.fingerprint}


@frappe.whitelist(methods=["POST"])
def retry_team_ssh_key_sync(team: str, name: str) -> None:
	"""Retry replacing the desired keys on servers that use this key."""
	require_access(team, "server:ssh-key")
	key = frappe.get_doc("Team SSH Key", name)
	if key.team != team:
		frappe.throw(_("This SSH key does not belong to the Team."), frappe.PermissionError)
	key.queue_sync()


@frappe.whitelist(methods=["POST"])
def delete_team_ssh_key(team: str, name: str) -> None:
	"""Delete a key after it is removed from all servers."""
	require_access(team, "server:ssh-key")
	key = frappe.get_doc("Team SSH Key", name)
	if key.team != team:
		frappe.throw(_("This SSH key does not belong to the Team."), frappe.PermissionError)
	key.delete()
