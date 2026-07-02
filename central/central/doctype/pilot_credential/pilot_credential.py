# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document

TOKEN_LENGTH = 48  # hex chars of the opaque bearer token (~192 bits of entropy)


class PilotCredential(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset: DF.Link | None
		pilot_credential_id: DF.Data
		expires_at: DF.Datetime | None
		last_used_at: DF.Datetime | None
		status: DF.Literal["Active", "Revoked"]
		team: DF.Link
		token_hash: DF.Data | None
	# end: auto-generated types

	_DOCTYPE_NAME = "Pilot Credential"

	@staticmethod
	def _hash(token: str) -> str:
		"""Deterministic, indexable one-way hash for lookup. The token is high-entropy,
		so plain SHA-256 suffices — no salted/slow password hash needed."""
		return hashlib.sha256(token.encode()).hexdigest()

	@classmethod
	def mint(cls, team: str, pilot_credential_id: str, asset: str | None = None, expires_at=None) -> str:
		"""Issue a pilot's credential and return the plaintext token once. Idempotent per
		pilot_credential_id: re-minting an existing pilot rotates its token in place."""
		name, pcid = cls._DOCTYPE_NAME, pilot_credential_id

		doc = frappe.get_doc(name, pcid) if frappe.db.exists(name, pcid) else frappe.new_doc(name)

		doc.pilot_credential_id = pcid
		doc.team = team
		doc.asset = asset
		doc.expires_at = expires_at

		return doc._issue_token()

	@classmethod
	def verify(cls, token: str) -> "PilotCredential | None":
		"""Resolve a bearer token to its usable credential, stamping last_used_at. The
		auth surface turns a None here into a 401."""
		token_hash = cls._hash(token) if token else None
		name = frappe.db.get_value(cls._DOCTYPE_NAME, {"token_hash": token_hash}) if token_hash else None

		if not name:
			return None

		doc = frappe.get_doc(cls._DOCTYPE_NAME, name)

		# Re-check the hash against the freshly loaded row. The lookup and this load are two
		# reads; under READ COMMITTED a rotate() committing a new token_hash between them
		# would otherwise admit the superseded token once (the name still resolves, and
		# is_usable() only checks status/expiry). Reject if the row no longer holds it.
		if doc.token_hash != token_hash or not doc.is_usable():
			return None

		doc.db_set("last_used_at", frappe.utils.now_datetime(), update_modified=False)

		return doc

	def is_usable(self) -> bool:
		if self.status != "Active":
			return False

		if self.expires_at and frappe.utils.get_datetime(self.expires_at) < frappe.utils.now_datetime():
			return False

		return True

	def rotate(self) -> str:
		"""Replace the token, invalidating the old one. Returns the new plaintext once."""
		return self._issue_token()

	def revoke(self) -> None:
		if self.status != "Revoked":
			self.db_set("status", "Revoked")

	# --- lifecycle joins: driven by the Atlas VM events once they echo the id back ---

	@classmethod
	def link_asset(cls, pilot_credential_id: str | None, asset: str | None) -> None:
		"""
		Bind a credential to the VM (Asset) it runs on. Called from the VM mirror once
		Atlas echoes the id back; idempotent and a no-op until both are known.
		"""
		if pilot_credential_id and asset and frappe.db.exists(cls._DOCTYPE_NAME, pilot_credential_id):
			frappe.db.set_value(cls._DOCTYPE_NAME, pilot_credential_id, "asset", asset)

	@classmethod
	def revoke_by_id(cls, pilot_credential_id: str | None) -> None:
		"""Revoke a pilot's credential when its VM is gone. No-op if unknown/absent."""
		if pilot_credential_id and frappe.db.exists(cls._DOCTYPE_NAME, pilot_credential_id):
			frappe.get_doc(cls._DOCTYPE_NAME, pilot_credential_id).revoke()

	@classmethod
	def rotate_by_id(cls, pilot_credential_id: str) -> str:
		"""Re-issue a live pilot's token (entry point for Atlas-driven rotation). Returns
		the new plaintext once, for Atlas to push into the bench's bench.toml."""
		return frappe.get_doc(cls._DOCTYPE_NAME, pilot_credential_id).rotate()

	def _issue_token(self) -> str:
		"""(Re)set this credential to a fresh Active token; return the plaintext once."""
		token = frappe.generate_hash(length=TOKEN_LENGTH)

		self.token_hash = self._hash(token)
		self.status = "Active"
		self.last_used_at = None
		# system-internal path; no user
		self.save(ignore_permissions=True)

		return token
