import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from central.api.jwks import get_atlas_jwks, jwks_document
from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.sso import ATLAS_TOKEN_TTL, mint_atlas_token, mint_bench_login


class TestAtlasSSO(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		frappe.db.set_single_value(
			"Central SSO Settings",
			{"atlas_key_id": None, "atlas_public_key": None, "atlas_private_key": None},
		)
		remove_encrypted_password("Central SSO Settings", "Central SSO Settings", "atlas_private_key")

	def initialize(self) -> CentralSSOSettings:
		settings = CentralSSOSettings.instance()
		settings.initialize_atlas_signing_key()
		return settings

	def test_public_read_does_not_initialize_keys(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		self.assertEqual(json.loads(get_atlas_jwks().get_data()), {"keys": []})
		self.assertFalse(CentralSSOSettings.instance().atlas_key_id)

	def test_mint_requires_operator_initialization(self):
		with self.assertRaises(frappe.ValidationError):
			mint_atlas_token(42)

	def test_non_operator_cannot_initialize(self):
		settings = CentralSSOSettings.instance()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			settings.initialize_atlas_signing_key()

	def test_stale_initializer_keeps_existing_key(self):
		stale = CentralSSOSettings.instance()
		settings = self.initialize()

		self.assertEqual(stale.initialize_atlas_signing_key(), settings.atlas_key_id)
		self.assertEqual(stale.atlas_signing_key(), settings.atlas_signing_key())

	def test_incomplete_key_is_not_overwritten(self):
		frappe.db.set_single_value("Central SSO Settings", "atlas_public_key", "incomplete")

		with self.assertRaises(frappe.ValidationError):
			self.initialize()

	def test_atlas_key_publication_is_separate_and_public_only(self):
		settings = self.initialize()
		key = json.loads(get_atlas_jwks().get_data())["keys"][0]

		self.assertEqual(key["kid"], settings.atlas_key_id)
		self.assertTrue(key["kid"].startswith("central:"))
		self.assertEqual((key["kty"], key["crv"], key["alg"]), ("OKP", "Ed25519", "EdDSA"))
		self.assertNotIn("d", key)
		self.assertNotIn(key["kid"], [key["kid"] for key in jwks_document()["keys"]])

	def test_token_has_regional_authority_and_short_expiry(self):
		settings = self.initialize()
		key = jwt.PyJWK.from_dict(settings.atlas_jwks()["keys"][0])
		claims = jwt.decode(
			mint_atlas_token(42), key.key, algorithms=["EdDSA"], audience="atlas-admin:42", issuer="central"
		)

		self.assertEqual((claims["sub"], claims["scope"], claims["tenant"]), ("central", "*", "*"))
		self.assertEqual(claims["exp"] - claims["iat"], ATLAS_TOKEN_TTL)

	def test_invalid_region_is_rejected_before_signing(self):
		for value in (-1, 65536, True, "42", None):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				mint_atlas_token(value)

	def test_pilot_keeps_its_rsa_contract(self):
		self.initialize()
		token = mint_bench_login("pilot-audience")
		key = jwt.PyJWK.from_dict(jwks_document()["keys"][0])
		self.assertEqual(jwt.get_unverified_header(token)["alg"], "RS256")
		claims = jwt.decode(token, key.key, algorithms=["RS256"], audience="pilot-audience")
		self.assertEqual(claims["scope"], "bench")

	@skipUnless(importlib.util.find_spec("admin"), "Requires the pinned Pilot checkout on PYTHONPATH")
	def test_real_pilot_verifier_accepts_login_and_rejects_wrong_audience(self):
		from admin.backend.internal.jwks_cache import JwksCache
		from admin.backend.internal.session import Session

		token = mint_bench_login("pilot-audience")
		with TemporaryDirectory() as directory:
			configuration = SimpleNamespace(
				jwks_url="https://central.example/jwks", jwks_audience="pilot-audience", jwt_secret=""
			)
			bench = SimpleNamespace(
				path=Path(directory) / "bench", config=SimpleNamespace(admin=configuration)
			)
			bench.path.mkdir()
			self.assertTrue(JwksCache(Path(directory), configuration.jwks_url).seed(jwks_document()))
			session = Session(bench)
			self.assertEqual(session.verify_token(token)["scope"], "bench")
			self.assertIsNone(session.verify_token(mint_bench_login("other-pilot")))

	@skipUnless(
		importlib.util.find_spec("atlas"), "Requires the pinned Atlas checkout in the validation bench"
	)
	def test_real_atlas_verifier_accepts_central_and_rejects_wrong_region(self):
		from atlas.auth.jwks import TrustedKeys, validate_central_jwks
		from atlas.auth.token import TokenValidator

		settings = self.initialize()
		keys = validate_central_jwks(settings.atlas_jwks())
		trusted = TrustedKeys(
			document={"keys": keys}, keys={key["kid"]: jwt.PyJWK.from_dict(key) for key in keys}
		)
		correct = mint_atlas_token(42)
		incorrect = mint_atlas_token(43)
		pilot_token = mint_bench_login("atlas-admin:42")

		with (
			patch(
				"atlas.auth.token.frappe.get_cached_doc",
				return_value=SimpleNamespace(region_id=42, admin_audience_id="atlas-admin:42"),
			),
			patch("atlas.auth.token.trusted_keys", return_value=trusted),
		):
			self.assertEqual(TokenValidator().claims(correct)["tenant"], "*")
			self.assertIsNone(TokenValidator().claims(incorrect))
			self.assertIsNone(TokenValidator().claims(pilot_token))
