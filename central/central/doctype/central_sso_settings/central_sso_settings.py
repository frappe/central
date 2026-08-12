# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document

# Central's single asymmetric signing key. Central signs downward tokens (bench-login,
# site-login) with the private half; benches hold only the public half (fetched from the
# JWKS endpoint) and verify offline. A compromised bench can therefore forge nothing.

RSA_KEY_SIZE = 2048
ALGORITHM = "RS256"


class CentralSSOSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

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
		frappe.db.commit()
