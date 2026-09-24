from __future__ import annotations

import base64
import binascii
import hashlib
import json

import frappe
from cryptography.exceptions import UnsupportedAlgorithm
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES


class TeamSSHKey(Document):
	"""One public login key owned by a Team and selected by individual servers."""

	def validate(self) -> None:
		self.title = (self.title or "").strip()
		self.public_key = (self.public_key or "").strip()
		if not self.title:
			frappe.throw(_("Enter a name for the SSH key."))
		if len(self.title) > 140:
			frappe.throw(_("Use a shorter SSH key name."))
		if not self.is_new() and self.has_value_changed("team"):
			frappe.throw(_("An SSH key cannot move to another Team."))
		if self.has_value_changed("public_key"):
			self.last_sync_error = None
		self.fingerprint = fingerprint(self.public_key)
		if frappe.db.exists(
			"Team SSH Key", {"team": self.team, "fingerprint": self.fingerprint, "name": ["!=", self.name]}
		):
			frappe.throw(_("This SSH key already belongs to the Team."))

	def on_update(self) -> None:
		if self.has_value_changed("public_key"):
			self.queue_sync()

	def on_trash(self) -> None:
		if frappe.db.exists("Server SSH Key", {"team_ssh_key": self.name}):
			frappe.throw(_("Remove this key from its servers before deleting it."))
		requests = frappe.get_all(
			"Resource Action",
			filters={"team": self.team, "action": "create", "status": ["in", PENDING_STATES]},
			fields=["request_payload"],
		)
		if any(
			self.name in json.loads(row.request_payload or "{}").get("ssh_key_ids", []) for row in requests
		):
			frappe.throw(_("Wait for pending server creation before deleting this key."))

	def queue_sync(self) -> None:
		frappe.enqueue(
			"central.integrations.ssh_keys.sync_team_ssh_key",
			name=self.name,
			queue="long",
			enqueue_after_commit=True,
		)


def fingerprint(public_key: str) -> str:
	"""Validate an OpenSSH public key and return its SHA256 fingerprint."""
	from cryptography.hazmat.primitives.serialization import load_ssh_public_key

	if not public_key or len(public_key) > 16_384 or "\n" in public_key or "\r" in public_key:
		frappe.throw(_("Enter one valid OpenSSH public key. Private keys are not accepted."))
	try:
		key = load_ssh_public_key(public_key.encode())
		parts = public_key.split(maxsplit=2)
		if len(parts) not in (2, 3):
			raise ValueError
		blob = base64.b64decode(parts[1], validate=True)
		if not blob or key is None:
			raise ValueError
	except ValueError, TypeError, binascii.Error, UnsupportedAlgorithm:
		frappe.throw(_("Enter one valid OpenSSH public key. Private keys are not accepted."))
	return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def on_doctype_update() -> None:
	frappe.db.add_unique("Team SSH Key", ["team", "fingerprint"])
