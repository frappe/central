# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import frappe
from frappe import _
from frappe.model.document import Document

from central.iam import user_has_operator_bypass

if TYPE_CHECKING:
	from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ALGORITHM = "EdDSA"

SigningPlane = Literal["atlas", "pilot"]


@dataclass(frozen=True)
class SigningKeyFields:
	"""The fields that hold one plane's Ed25519 signing key."""

	label: str
	key_id: str
	public_key: str
	private_key: str


SIGNING_KEYS: dict[str, SigningKeyFields] = {
	"atlas": SigningKeyFields("Atlas", "atlas_key_id", "atlas_public_key", "atlas_private_key"),
	"pilot": SigningKeyFields("Pilot", "pilot_key_id", "pilot_public_key", "pilot_private_key"),
}


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
		pilot_key_id: DF.Data | None
		pilot_private_key: DF.Password | None
		pilot_public_key: DF.Code | None
	# end: auto-generated types

	@classmethod
	def instance(cls) -> "CentralSSOSettings":
		return frappe.get_single("Central SSO Settings")

	def before_validate(self) -> None:
		if self.issuer_url:
			self.issuer_url = self.issuer_url.strip().rstrip("/")

	@frappe.whitelist(methods=["POST"])
	def initialize_signing_key(self, plane: SigningPlane) -> str:
		"""Create the signing key for one plane once, under an operator-held database lock."""
		fields = get_signing_key_fields(plane)
		if not user_has_operator_bypass():
			frappe.throw(
				_("Only an operator can initialize the {0} signing key.").format(fields.label),
				frappe.PermissionError,
			)
		self.check_permission("write")

		# Singles have no parent row. This existing metadata row serializes first initialization.
		frappe.db.get_value("DocType", self.doctype, "name", for_update=True)
		self.flags.for_update = True
		self.reload()

		if self.get(fields.key_id):
			self._get_private_key(fields)
			return self.get(fields.key_id)

		if self.get(fields.public_key) or self.get_password(fields.private_key, raise_exception=False):
			throw_incomplete_signing_key(fields)

		self._generate_keypair(fields)
		self.save()
		self.add_comment(
			"Info", _("Initialized {0} signing key {1}.").format(fields.label, self.get(fields.key_id))
		)
		return self.get(fields.key_id)

	def get_signing_key(self, plane: SigningPlane) -> tuple[str, str]:
		"""The PEM private key and `kid` for one plane. A missing key blocks signing."""
		fields = get_signing_key_fields(plane)
		self._require_key_id(fields)
		return self._get_private_key(fields), self.get(fields.key_id)

	def get_public_key(self, plane: SigningPlane) -> Ed25519PublicKey:
		"""The Ed25519 public key that verifies one plane's tokens."""
		from cryptography.hazmat.primitives.serialization import load_pem_public_key

		fields = get_signing_key_fields(plane)
		self._require_key_id(fields)
		if not self.get(fields.public_key):
			throw_incomplete_signing_key(fields)
		return load_pem_public_key(self.get(fields.public_key).encode())

	def get_jwks(self, plane: SigningPlane) -> dict:
		"""Publish one plane's public key, without creating or rotating keys."""
		from jwt.algorithms import OKPAlgorithm

		key_id = self.get(get_signing_key_fields(plane).key_id)
		if not key_id:
			return {"keys": []}

		key = OKPAlgorithm.to_jwk(self.get_public_key(plane), as_dict=True)
		key.update({"kid": key_id, "use": "sig", "alg": ALGORITHM})
		return {"keys": [key]}

	def _require_key_id(self, fields: SigningKeyFields) -> None:
		if not self.get(fields.key_id):
			frappe.throw(
				_("Initialize the {0} signing key in Central SSO Settings before you use it.").format(
					fields.label
				)
			)

	def _get_private_key(self, fields: SigningKeyFields) -> str:
		private_key = self.get_password(fields.private_key, raise_exception=False)
		if not self.get(fields.public_key) or not private_key:
			throw_incomplete_signing_key(fields)
		return private_key

	def _generate_keypair(self, fields: SigningKeyFields) -> None:
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		key = Ed25519PrivateKey.generate()
		private_key = key.private_bytes(
			serialization.Encoding.PEM,
			serialization.PrivateFormat.PKCS8,
			serialization.NoEncryption(),
		).decode()
		public_key = (
			key.public_key()
			.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
			.decode()
		)

		self.set(fields.private_key, private_key)
		self.set(fields.public_key, public_key)
		self.set(fields.key_id, f"central:{frappe.generate_hash(length=16)}")


def get_signing_key_fields(plane: str) -> SigningKeyFields:
	if plane not in SIGNING_KEYS:
		frappe.throw(_("Unknown signing plane {0}.").format(plane))
	return SIGNING_KEYS[plane]


def throw_incomplete_signing_key(fields: SigningKeyFields) -> None:
	frappe.throw(
		_("The {0} signing key is incomplete. Restore its saved configuration.").format(fields.label)
	)
