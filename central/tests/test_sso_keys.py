# Copyright (c) 2026, frappe and Contributors
# See license.txt

import json
import time

import frappe
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from central.api.jwks import get_jwks, jwks_document
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM, CentralSSOSettings
from central.sso import mint_bench_login

DOCTYPE = "Central SSO Settings"


def reset_signing_key(plane: str) -> None:
	"""Remove one plane's key so a test starts from an uninitialized deployment."""
	frappe.db.set_single_value(
		DOCTYPE, {f"{plane}_key_id": None, f"{plane}_public_key": None, f"{plane}_private_key": None}
	)
	remove_encrypted_password(DOCTYPE, DOCTYPE, f"{plane}_private_key")


class TestPilotSigningKey(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		reset_signing_key("pilot")
		reset_signing_key("atlas")

	def initialize(self) -> CentralSSOSettings:
		settings = CentralSSOSettings.instance()
		settings.initialize_signing_key("pilot")
		return settings

	def test_public_read_does_not_initialize_the_key(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		self.assertEqual(json.loads(get_jwks().get_data()), {"keys": []})
		self.assertFalse(CentralSSOSettings.instance().pilot_key_id)

	def test_mint_requires_operator_initialization(self):
		with self.assertRaises(frappe.ValidationError):
			mint_bench_login("pilot-audience")
		self.assertFalse(CentralSSOSettings.instance().pilot_key_id)

	def test_non_operator_cannot_initialize(self):
		settings = CentralSSOSettings.instance()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			settings.initialize_signing_key("pilot")

	def test_unknown_plane_is_rejected(self):
		# Newer Frappe rejects a value outside the Literal before the method runs.
		with self.assertRaises((frappe.ValidationError, frappe.FrappeTypeError)):
			CentralSSOSettings.instance().initialize_signing_key("billing")

	def test_stale_initializer_keeps_existing_key(self):
		stale = CentralSSOSettings.instance()
		settings = self.initialize()

		self.assertEqual(stale.initialize_signing_key("pilot"), settings.pilot_key_id)
		self.assertEqual(stale.get_signing_key("pilot"), settings.get_signing_key("pilot"))

	def test_incomplete_key_is_not_overwritten(self):
		frappe.db.set_single_value(DOCTYPE, "pilot_public_key", "incomplete")

		with self.assertRaises(frappe.ValidationError):
			self.initialize()

	def test_endpoint_publishes_the_initialized_pilot_public_key(self):
		"""Pilot's JWKS cache reads `keys` at the top level, without the message envelope."""
		settings = self.initialize()
		body = json.loads(get_jwks().get_data())

		self.assertNotIn("message", body)
		[key] = body["keys"]
		self.assertEqual(key["kid"], settings.pilot_key_id)
		self.assertTrue(key["kid"].startswith("central:"))
		self.assertEqual(
			(key["kty"], key["crv"], key["alg"], key["use"]), ("OKP", "Ed25519", ALGORITHM, "sig")
		)
		self.assertNotIn("d", key)

	def test_endpoint_publishes_both_public_keys_without_rotating_them(self):
		settings = self.initialize()
		settings.initialize_signing_key("atlas")
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		body = json.loads(get_jwks().get_data())
		self.assertNotEqual(settings.pilot_key_id, settings.atlas_key_id)
		self.assertNotIn("message", body)
		self.assertEqual([key["kid"] for key in body["keys"]], [settings.pilot_key_id, settings.atlas_key_id])
		for key in body["keys"]:
			self.assertEqual(
				(key["kty"], key["crv"], key["alg"], key["use"]), ("OKP", "Ed25519", ALGORITHM, "sig")
			)
			self.assertNotIn("d", key)
		self.assertEqual(jwks_document(), body)
		saved = CentralSSOSettings.instance()
		self.assertEqual(
			(saved.pilot_key_id, saved.atlas_key_id), (settings.pilot_key_id, settings.atlas_key_id)
		)

	def test_endpoint_publishes_atlas_when_pilot_is_uninitialized(self):
		settings = CentralSSOSettings.instance()
		settings.initialize_signing_key("atlas")

		self.assertEqual(json.loads(get_jwks().get_data()), settings.get_jwks("atlas"))
		self.assertFalse(CentralSSOSettings.instance().pilot_key_id)

	def test_endpoint_rejects_an_incomplete_atlas_key(self):
		self.initialize()
		frappe.db.set_single_value(DOCTYPE, "atlas_key_id", "central:incomplete")

		with self.assertRaises(frappe.ValidationError):
			get_jwks()

	def test_token_signed_by_central_verifies_against_published_jwks(self):
		self.initialize()
		token = mint_bench_login("pilot-audience")
		key = jwt.PyJWKSet.from_dict(jwks_document())[jwt.get_unverified_header(token)["kid"]]

		claims = jwt.decode(token, key.key, algorithms=[ALGORITHM], audience="pilot-audience")
		self.assertEqual((claims["sub"], claims["scope"]), ("admin", "bench"))

	def test_a_forged_token_is_rejected(self):
		settings = self.initialize()
		attacker = Ed25519PrivateKey.generate().private_bytes(
			serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
		)
		now = int(time.time())
		token = jwt.encode(
			{"sub": "admin", "iat": now, "exp": now + 60},
			attacker,
			algorithm=ALGORITHM,
			headers={"kid": settings.pilot_key_id},
		)

		key = jwt.PyJWK.from_dict(jwks_document()["keys"][0])
		with self.assertRaises(jwt.InvalidSignatureError):
			jwt.decode(token, key.key, algorithms=[ALGORITHM], options={"verify_aud": False})


class TestIssuerURL(IntegrationTestCase):
	def test_issuer_url_drops_trailing_slashes(self):
		# Cleanups run last first: roll back, then drop the cached copy of the saved value.
		self.addCleanup(frappe.clear_document_cache, DOCTYPE, DOCTYPE)
		self.addCleanup(frappe.db.rollback)
		settings = CentralSSOSettings.instance()
		settings.issuer_url = " https://central.example.test// "
		settings.save()

		self.assertEqual(settings.issuer_url, "https://central.example.test")
