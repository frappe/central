# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Ed25519 signing for entitlement tokens.

Central signs with a private key (site config). The cluster verifies offline
with only the public key — so a compromised/buggy Agent cannot mint a higher
cap. The canonical payload encoding must match on both sides.
"""

import base64
import json

import frappe
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical(payload: dict) -> bytes:
	"""Deterministic bytes for signing/verifying (sorted keys, compact)."""
	return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def generate_keypair() -> tuple[str, str]:
	"""Return (private_b64, public_b64) raw Ed25519 keys for one-time setup."""
	key = Ed25519PrivateKey.generate()
	private = key.private_bytes(
		serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
	)
	public = key.public_key().public_bytes(
		serialization.Encoding.Raw, serialization.PublicFormat.Raw
	)
	return base64.b64encode(private).decode(), base64.b64encode(public).decode()


def _private_key() -> Ed25519PrivateKey:
	b64 = frappe.conf.get("entitlement_private_key")
	if not b64:
		frappe.throw("entitlement_private_key is not configured in site config")
	return Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64))


def sign_payload(payload: dict) -> str:
	return base64.b64encode(_private_key().sign(canonical(payload))).decode()


def verify_payload(payload: dict, signature_b64: str, public_key_b64: str) -> bool:
	try:
		public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
		public_key.verify(base64.b64decode(signature_b64), canonical(payload))
		return True
	except (InvalidSignature, ValueError):
		return False
