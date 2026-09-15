# Copyright (c) 2026, frappe and Contributors
# See license.txt

import json
import time

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from jwt.algorithms import OKPAlgorithm

from central.api.jwks import get_jwks, jwks_document
from central.central.doctype.central_sso_settings.central_sso_settings import (
	ALGORITHM,
	KEY_NAMESPACE,
	KEY_PROPAGATION_SECONDS,
	CentralSSOSettings,
)

# Atlas refuses a key set that carries anything else (atlas/auth/jwks.py).
ATLAS_JWK_FIELDS = {"alg", "crv", "d", "key_ops", "kid", "kty", "use", "x"}


class TestSSOKeys(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Start from an un-keyed singleton so generation is exercised deterministically.
		settings = CentralSSOSettings.instance()
		settings.signing_keys = []
		settings.save(ignore_permissions=True)

	def test_jwks_is_empty_until_a_key_exists(self):
		self.assertEqual(jwks_document(), {"keys": []})

	def test_signing_key_generates_an_ed25519_keypair(self):
		private_pem, kid = CentralSSOSettings.instance().signing_key()

		self.assertIn("BEGIN PRIVATE KEY", private_pem)
		self.assertTrue(kid.startswith(f"{KEY_NAMESPACE}:"))
		self.assertTrue(kid.removeprefix(f"{KEY_NAMESPACE}:"))

	def test_the_published_key_set_is_one_atlas_accepts(self):
		"""Every rule atlas/auth/jwks.py enforces on a Central key set."""
		CentralSSOSettings.instance().signing_key()

		keys = jwks_document()["keys"]
		self.assertTrue(1 <= len(keys) <= 100)
		for jwk in keys:
			self.assertEqual(set(jwk) - ATLAS_JWK_FIELDS, set())
			self.assertNotIn("d", jwk)
			self.assertEqual(jwk["kty"], "OKP")
			self.assertEqual(jwk["crv"], "Ed25519")
			self.assertEqual(jwk["alg"], "EdDSA")
			self.assertEqual(jwk["use"], "sig")
			self.assertTrue(jwk["kid"].startswith(f"{KEY_NAMESPACE}:"))
		self.assertEqual(len({jwk["kid"] for jwk in keys}), len(keys))

	def test_rotation_publishes_both_keys(self):
		first = CentralSSOSettings.instance().rotate_key()
		second = CentralSSOSettings.instance().rotate_key()

		self.assertNotEqual(first, second)
		self.assertEqual([key["kid"] for key in jwks_document()["keys"]], [first, second])

	def test_a_new_key_is_published_before_it_signs(self):
		"""A verifier checks against a cached key set and does not re-fetch on an unknown
		key id, so signing with a key it has not seen yet would have its tokens refused."""
		established = CentralSSOSettings.instance().rotate_key()
		self._backdate(established)
		fresh = CentralSSOSettings.instance().rotate_key()

		self.assertEqual(CentralSSOSettings.instance().signing_key()[1], established)
		self.assertIn(fresh, [key["kid"] for key in jwks_document()["keys"]])

	def test_a_key_signs_once_it_has_propagated(self):
		CentralSSOSettings.instance().rotate_key()
		expected = CentralSSOSettings.instance().rotate_key()
		self._backdate(expected)

		self.assertEqual(CentralSSOSettings.instance().signing_key()[1], expected)

	def test_the_very_first_key_signs_at_once(self):
		"""Nothing has fetched the set yet, so there is no cached copy to miss it."""
		private_pem, kid = CentralSSOSettings.instance().signing_key()

		self.assertTrue(private_pem)
		self.assertEqual(CentralSSOSettings.instance().signing_keys[-1].kid, kid)

	@staticmethod
	def _backdate(kid: str) -> None:
		"""Age a key past the propagation window, as the clock would."""
		settings = CentralSSOSettings.instance()
		for key in settings.signing_keys:
			if key.kid == kid:
				key.db_set(
					"published_at",
					frappe.utils.add_to_date(
						frappe.utils.now_datetime(), seconds=-(KEY_PROPAGATION_SECONDS + 60)
					),
					update_modified=False,
				)
		frappe.clear_document_cache("Central SSO Settings")

	def test_a_token_from_a_retired_key_still_verifies_while_it_is_published(self):
		"""The point of publishing more than one key: rotating must not invalidate a
		token that is still inside its lifetime."""
		old_private, old_kid = CentralSSOSettings.instance().signing_key()
		token = self._token(old_private, old_kid)
		self._backdate(CentralSSOSettings.instance().rotate_key())

		jwk = next(key for key in jwks_document()["keys"] if key["kid"] == old_kid)
		claims = jwt.decode(
			token, OKPAlgorithm.from_jwk(jwk), algorithms=[ALGORITHM], audience="atlas-admin:42"
		)
		self.assertEqual(claims["iss"], "central")

	def test_endpoint_serves_raw_jwks_without_the_message_envelope(self):
		CentralSSOSettings.instance().signing_key()

		body = json.loads(get_jwks().get_data())

		self.assertIn("keys", body)
		self.assertNotIn("message", body)

	def test_a_forged_token_is_rejected(self):
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		_, kid = CentralSSOSettings.instance().signing_key()
		attacker = (
			Ed25519PrivateKey.generate()
			.private_bytes(
				encoding=serialization.Encoding.PEM,
				format=serialization.PrivateFormat.PKCS8,
				encryption_algorithm=serialization.NoEncryption(),
			)
			.decode()
		)
		token = self._token(attacker, kid)

		public_key = OKPAlgorithm.from_jwk(jwks_document()["keys"][0])
		with self.assertRaises(jwt.InvalidSignatureError):
			jwt.decode(token, public_key, algorithms=[ALGORITHM], options={"verify_aud": False})

	def test_a_token_naming_an_unknown_key_is_refused(self):
		from central.sso import _public_key_for

		private_pem, _ = CentralSSOSettings.instance().signing_key()

		self.assertRaises(
			frappe.AuthenticationError, _public_key_for, self._token(private_pem, "central:missing")
		)

	@staticmethod
	def _token(private_pem: str, kid: str) -> str:
		now = int(time.time())
		return jwt.encode(
			{
				"iss": "central",
				"sub": "central",
				"aud": "atlas-admin:42",
				"scope": "*",
				"tenant": "*",
				"iat": now,
				"exp": now + 60,
			},
			private_pem,
			algorithm=ALGORITHM,
			headers={"kid": kid},
		)
