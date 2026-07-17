# Copyright (c) 2026, frappe and Contributors
# See license.txt

import time

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from jwt.algorithms import RSAAlgorithm

import json

from central.api.jwks import get_jwks, jwks_document
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM, CentralSSOSettings


class TestSSOKeys(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Start each test from an un-keyed singleton so generation is exercised deterministically.
		settings = CentralSSOSettings.instance()
		settings.db_set("kid", None)
		settings.db_set("public_key", None)
		settings.db_set("private_key", None)

	def test_jwks_is_empty_until_a_key_exists(self):
		self.assertEqual(jwks_document(), {"keys": []})

	def test_signing_key_generates_a_usable_keypair(self):
		private_pem, kid = CentralSSOSettings.instance().signing_key()
		self.assertTrue(kid)
		self.assertIn("BEGIN PRIVATE KEY", private_pem)

	def test_jwks_publishes_the_active_public_key(self):
		_, kid = CentralSSOSettings.instance().signing_key()
		keys = jwks_document()["keys"]
		self.assertEqual(len(keys), 1)
		jwk = keys[0]
		self.assertEqual(jwk["kid"], kid)
		self.assertEqual(jwk["kty"], "RSA")
		self.assertEqual(jwk["use"], "sig")
		self.assertEqual(jwk["alg"], ALGORITHM)

	def test_endpoint_serves_raw_jwks_without_the_message_envelope(self):
		"""A JWKS client (the bench's PyJWKClient) reads `keys` at the top level — the
		endpoint must not wrap it in Frappe's `{"message": ...}` envelope."""
		CentralSSOSettings.instance().signing_key()
		body = json.loads(get_jwks().get_data())
		self.assertIn("keys", body)
		self.assertNotIn("message", body)

	def test_token_signed_by_central_verifies_against_published_jwks(self):
		"""End-to-end: a bench reconstructs the public key from the JWKS and verifies a
		token Central signed with the private half."""
		private_pem, kid = CentralSSOSettings.instance().signing_key()
		now = int(time.time())
		token = jwt.encode(
			{"sub": "admin", "aud": "vm-1", "iss": "central", "iat": now, "exp": now + 60},
			private_pem,
			algorithm=ALGORITHM,
			headers={"kid": kid},
		)

		jwk = jwks_document()["keys"][0]
		public_key = RSAAlgorithm.from_jwk(jwk)
		claims = jwt.decode(token, public_key, algorithms=[ALGORITHM], audience="vm-1", issuer="central")
		self.assertEqual(claims["sub"], "admin")

	def test_a_forged_token_is_rejected(self):
		"""A token signed by a different key must fail verification against the JWKS."""
		_, kid = CentralSSOSettings.instance().signing_key()
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric import rsa

		attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
			encoding=serialization.Encoding.PEM,
			format=serialization.PrivateFormat.PKCS8,
			encryption_algorithm=serialization.NoEncryption(),
		).decode()
		now = int(time.time())
		token = jwt.encode({"sub": "admin", "iat": now, "exp": now + 60}, attacker, algorithm=ALGORITHM,
				   headers={"kid": kid})

		public_key = RSAAlgorithm.from_jwk(jwks_document()["keys"][0])
		with self.assertRaises(jwt.InvalidSignatureError):
			jwt.decode(token, public_key, algorithms=[ALGORITHM], options={"verify_aud": False})
