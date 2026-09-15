# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from jwt.algorithms import OKPAlgorithm

from central.api.jwks import jwks_document
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM
from central.central.doctype.region.region import MAXIMUM_REGION_ID, Region
from central.sso import mint_proxy_token, mint_region_token

REGION = "test-region-tokens"
REGION_ID = 42


class TestRegionTokens(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_region(REGION, REGION_ID)

	@staticmethod
	def _ensure_region(region: str, region_id: int | None) -> str:
		"""Put the region back the way this class expects it, so one test's edit cannot
		decide what the next test sees."""
		if frappe.db.exists("Region", region):
			frappe.db.set_value("Region", region, "region_id", region_id, update_modified=False)
		else:
			frappe.get_doc({"doctype": "Region", "region": region, "region_id": region_id}).insert(
				ignore_permissions=True
			)
		return region

	def _claims(self, token: str, audience: str) -> dict:
		"""Verify the way Atlas does: pick the key by kid, require EdDSA and iss=central."""
		kid = jwt.get_unverified_header(token)["kid"]
		jwk = next(key for key in jwks_document()["keys"] if key["kid"] == kid)
		return jwt.decode(
			token,
			OKPAlgorithm.from_jwk(jwk),
			algorithms=[ALGORITHM],
			audience=audience,
			issuer="central",
			options={"require": ["iss", "sub", "aud", "scope", "iat", "exp"]},
		)

	def test_a_region_token_carries_what_atlas_requires(self):
		claims = self._claims(mint_region_token(REGION), f"atlas-admin:{REGION_ID}")

		self.assertEqual(claims["iss"], "central")
		self.assertEqual(claims["scope"], "*")
		self.assertEqual(claims["tenant"], "*")
		self.assertTrue(claims["sub"])
		self.assertNotIn("constraints", claims)

	def test_a_region_token_is_signed_with_eddsa_and_a_namespaced_key(self):
		header = jwt.get_unverified_header(mint_region_token(REGION))

		self.assertEqual(header["alg"], "EdDSA")
		self.assertTrue(header["kid"].startswith("central:"))

	def test_a_proxy_token_names_no_tenant(self):
		"""The proxy routes for every tenant and refuses a token that names one."""
		claims = self._claims(mint_proxy_token(REGION), f"atlas-proxy:{REGION_ID}")

		self.assertNotIn("tenant", claims)
		self.assertEqual(claims["scope"], "*")

	def test_a_region_token_is_refused_by_another_region(self):
		token = mint_region_token(REGION)

		with self.assertRaises(jwt.InvalidAudienceError):
			self._claims(token, "atlas-admin:99")

	def test_a_region_token_is_not_accepted_as_a_proxy_token(self):
		token = mint_region_token(REGION)

		with self.assertRaises(jwt.InvalidAudienceError):
			self._claims(token, f"atlas-proxy:{REGION_ID}")

	def test_a_region_without_an_id_cannot_mint(self):
		"""A region exists before an operator reads its number off Atlas. Minting then
		refuses, rather than signing a token no region would accept."""
		unconfigured = self._ensure_region("test-region-unconfigured", None)

		self.assertRaises(frappe.ValidationError, mint_region_token, unconfigured)

	def test_region_zero_is_a_usable_region(self):
		"""Atlas accepts 0 through 65535, so 0 is a real region and not a stand-in for
		unset. Only NULL means unconfigured."""
		zero = self._ensure_region("test-region-zero", 0)

		self.assertEqual(Region.admin_audience(zero), "atlas-admin:0")
		self.assertEqual(frappe.get_doc("Region", zero).mesh_address_prefix, "fdaa:0")

	def test_the_region_id_stays_inside_sixteen_bits(self):
		region = frappe.get_doc("Region", REGION)
		for outside in (-1, MAXIMUM_REGION_ID + 1):
			with self.subTest(region_id=outside):
				region.region_id = outside

				self.assertRaises(frappe.ValidationError, region.save)

	def test_the_mesh_prefix_is_derived_from_the_region_id(self):
		self.assertEqual(frappe.get_doc("Region", REGION).mesh_address_prefix, "fdaa:2a")

	def test_two_regions_cannot_share_an_id(self):
		self.assertIsNotNone(frappe.db.get_column_index("tabRegion", "region_id", unique=True))

	def test_the_audiences_match_the_atlas_settings_form(self):
		self.assertEqual(Region.admin_audience(REGION), f"atlas-admin:{REGION_ID}")
		self.assertEqual(Region.proxy_audience(REGION), f"atlas-proxy:{REGION_ID}")
