# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

ALGORITHM = "EdDSA"
KEY_NAMESPACE = "central"
# A verifier checks against a cached copy of the key set and does not re-fetch on an
# unknown key id, so a key has to be published for longer than any consumer's refresh
# interval before it is safe to sign with. Atlas refreshes every 5 minutes.
KEY_PROPAGATION_SECONDS = 15 * 60


class CentralSSOSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.central.doctype.central_signing_key.central_signing_key import CentralSigningKey

		issuer_url: DF.Data | None
		signing_keys: DF.Table[CentralSigningKey]
	# end: auto-generated types

	@classmethod
	def instance(cls) -> "CentralSSOSettings":
		return frappe.get_single("Central SSO Settings")

	def signing_key(self) -> tuple[str, str]:
		"""The PEM private key and `kid` to sign with, generating one on first use.
		Only the authenticated minting path calls this, so key generation never rides
		a guest request."""
		if not self.signing_keys:
			self.rotate_key()
		key = self._key_to_sign_with()
		return key.get_password("private_key"), key.kid

	def _key_to_sign_with(self):
		"""The newest key that consumers have had time to fetch.

		A freshly added key is published but does not sign yet: a verifier holding a
		cached key set would refuse its tokens until the next refresh. Before anything
		has been published there is no such consumer, so the first key signs at once."""
		propagated = [key for key in self.signing_keys if self._has_propagated(key)]
		return propagated[-1] if propagated else self.signing_keys[-1]

	@staticmethod
	def _has_propagated(key) -> bool:
		age = frappe.utils.now_datetime() - frappe.utils.get_datetime(key.published_at)
		return age.total_seconds() >= KEY_PROPAGATION_SECONDS

	def verification_key(self, kid: str):
		"""The public key for one `kid`, for a token Central itself minted."""
		from cryptography.hazmat.primitives.serialization import load_pem_public_key

		for key in self.signing_keys:
			if key.kid == kid:
				return load_pem_public_key(key.public_key.encode())
		frappe.throw(_("Unknown signing key {0}.").format(kid), frappe.AuthenticationError)

	def jwks(self) -> dict:
		"""The published key set. Empty until a key exists — a read never generates
		one, which keeps generation off the guest path."""
		return {"keys": [self._public_jwk(key) for key in self.signing_keys]}

	@frappe.whitelist()
	def rotate_key(self) -> str:
		"""Publish a new signing key. It starts signing once consumers have had time to
		fetch it, and the keys already here stay published, so rotating breaks neither
		the tokens already minted nor the ones minted next."""
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		key = Ed25519PrivateKey.generate()
		row = self.append(
			"signing_keys",
			{
				"kid": f"{KEY_NAMESPACE}:{frappe.generate_hash(length=16)}",
				"published_at": frappe.utils.now_datetime(),
				"public_key": key.public_key()
				.public_bytes(
					encoding=serialization.Encoding.PEM,
					format=serialization.PublicFormat.SubjectPublicKeyInfo,
				)
				.decode(),
				"private_key": key.private_bytes(
					encoding=serialization.Encoding.PEM,
					format=serialization.PrivateFormat.PKCS8,
					encryption_algorithm=serialization.NoEncryption(),
				).decode(),
			},
		)
		self.save(ignore_permissions=True)
		return row.kid

	@staticmethod
	def _public_jwk(key) -> dict:
		"""A JWK carrying only the fields Atlas accepts; anything else is refused."""
		from cryptography.hazmat.primitives.serialization import load_pem_public_key
		from jwt.algorithms import OKPAlgorithm

		jwk = OKPAlgorithm.to_jwk(load_pem_public_key(key.public_key.encode()), as_dict=True)
		jwk.update({"kid": key.kid, "use": "sig", "alg": ALGORITHM})
		return jwk
