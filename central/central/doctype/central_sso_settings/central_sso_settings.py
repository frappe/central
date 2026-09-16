# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.iam import user_has_operator_bypass

RSA_KEY_SIZE = 2048
ALGORITHM = "RS256"
ATLAS_ALGORITHM = "EdDSA"


class CentralSSOSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_key_id: DF.Data | None
		atlas_private_key: DF.Password | None
		atlas_public_key: DF.Code | None
		issuer_url: DF.Data | None
		kid: DF.Data | None
		private_key: DF.Password | None
		public_key: DF.Code | None
	# end: auto-generated types

	@classmethod
	def instance(cls) -> "CentralSSOSettings":
		return frappe.get_single("Central SSO Settings")

	def signing_key(self) -> tuple[str, str]:
		"""The active PEM private key and its `kid`, generating the keypair on first use.
		Only the (authenticated) minting path calls this, so key generation never rides a
		guest request."""
		if not self.kid:
			self._generate_keypair()
		return self.get_password("private_key"), self.kid

	def jwks(self) -> dict:
		"""The public JWKS document benches verify against. Empty until a key exists — a
		read never generates one (that stays on the signing path)."""
		if not self.kid:
			return {"keys": []}
		return {"keys": [self._public_jwk()]}

	@frappe.whitelist(methods=["POST"])
	def initialize_atlas_signing_key(self) -> str:
		"""Create the regional signing key once, under an operator-held database lock."""
		if not user_has_operator_bypass():
			frappe.throw(_("Only an operator can initialize the Atlas signing key."), frappe.PermissionError)
		self.check_permission("write")

		# Singles have no parent row. This existing metadata row serializes first initialization.
		frappe.db.get_value("DocType", self.doctype, "name", for_update=True)
		self.flags.for_update = True
		self.reload()

		if self.atlas_key_id:
			if not self.atlas_public_key or not self.atlas_private_key:
				frappe.throw(_("The Atlas signing key is incomplete. Restore its saved configuration."))
			return self.atlas_key_id

		if self.atlas_public_key or self.get_password("atlas_private_key", raise_exception=False):
			frappe.throw(_("The Atlas signing key is incomplete. Restore its saved configuration."))

		self._generate_atlas_keypair()
		self.save()
		self.add_comment("Info", _("Initialized Atlas signing key {0}.").format(self.atlas_key_id))
		return self.atlas_key_id

	def atlas_signing_key(self) -> tuple[str, str]:
		private_key = self.get_password("atlas_private_key", raise_exception=False)
		if not self.atlas_key_id or not self.atlas_public_key or not private_key:
			frappe.throw(
				_("Initialize the Atlas signing key in Central SSO Settings before making regional requests.")
			)

		return private_key, self.atlas_key_id

	def atlas_jwks(self) -> dict:
		"""Publish only Atlas-compatible public keys, without creating or rotating keys."""
		from cryptography.hazmat.primitives.serialization import load_pem_public_key
		from jwt.algorithms import OKPAlgorithm

		if not self.atlas_key_id:
			return {"keys": []}

		public_key = load_pem_public_key(self.atlas_public_key.encode())
		key = OKPAlgorithm.to_jwk(public_key, as_dict=True)
		key.update({"kid": self.atlas_key_id, "use": "sig", "alg": ATLAS_ALGORITHM})

		return {"keys": [key]}

	def _generate_atlas_keypair(self) -> None:
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		key = Ed25519PrivateKey.generate()
		self.atlas_private_key = key.private_bytes(
			serialization.Encoding.PEM,
			serialization.PrivateFormat.PKCS8,
			serialization.NoEncryption(),
		).decode()
		self.atlas_public_key = (
			key.public_key()
			.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
			.decode()
		)
		self.atlas_key_id = f"central:{frappe.generate_hash(length=16)}"

	def _public_jwk(self) -> dict:
		from cryptography.hazmat.primitives.serialization import load_pem_public_key
		from jwt.algorithms import RSAAlgorithm

		public_key = load_pem_public_key(self.public_key.encode())
		jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
		jwk.update({"kid": self.kid, "use": "sig", "alg": ALGORITHM})
		return jwk

	def _generate_keypair(self) -> None:
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric import rsa

		key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
		self.private_key = key.private_bytes(
			encoding=serialization.Encoding.PEM,
			format=serialization.PrivateFormat.PKCS8,
			encryption_algorithm=serialization.NoEncryption(),
		).decode()
		self.public_key = (
			key.public_key()
			.public_bytes(
				encoding=serialization.Encoding.PEM,
				format=serialization.PublicFormat.SubjectPublicKeyInfo,
			)
			.decode()
		)
		self.kid = frappe.generate_hash(length=16)
		# Password field → private key is encrypted at rest on save.
		self.save(ignore_permissions=True)
