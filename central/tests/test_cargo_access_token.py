"""The token Central presents to a Cargo host for bucket work: what it is audienced to,
and when the host's row gets one."""

from __future__ import annotations

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.sso import mint_cargo_bucket_access_token
from central.tests.utils import ensure_region

REGION = "cargo-token"
REGION_ID = 41
AUDIENCE = f"central-{REGION_ID}-bucket"
SCOPE = "central:cargo-bucket"


def claims_of(token: str) -> dict:
	settings = CentralSSOSettings.instance()

	return jwt.decode(
		token,
		settings.public_key,
		algorithms=["RS256"],
		audience=AUDIENCE,
	)


class IntegrationTestCargoAccessToken(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_region(REGION)
		frappe.db.set_value("Region", REGION, "atlas_region_id", REGION_ID)
		self.instance = self.cargo_instance(REGION)
		# These rows outlive a single test, so each one starts from an unregistered host.
		remove_encrypted_password("Cargo Instance", self.instance.name, "cargo_access_token")
		self.instance.db_set("status", "Draft")
		self.instance.reload()

	def cargo_instance(self, region: str):
		name = frappe.db.get_value("Cargo Instance", {"region": region})
		if name:
			return frappe.get_doc("Cargo Instance", name)

		return frappe.get_doc({"doctype": "Cargo Instance", "region": region}).insert(ignore_permissions=True)

	def test_the_token_is_audienced_to_the_region_it_was_minted_for(self):
		"""One taken from another region's traffic is refused by this host."""
		claims = claims_of(mint_cargo_bucket_access_token(self.instance))

		self.assertEqual(claims["aud"], AUDIENCE)
		self.assertEqual(claims["scope"], SCOPE)
		self.assertEqual(claims["instance"], self.instance.name)

	def test_a_region_atlas_does_not_know_gets_no_token(self):
		unmapped = "cargo-token-unmapped"
		ensure_region(unmapped)
		frappe.db.set_value("Region", unmapped, "atlas_region_id", 0)

		with self.assertRaises(frappe.ValidationError):
			mint_cargo_bucket_access_token(self.cargo_instance(unmapped))

	def test_registering_a_host_is_what_issues_its_token(self):
		self.assertIsNone(self.instance.get_password("cargo_access_token", raise_exception=False))

		self.instance.status = "Registered"
		self.instance.save(ignore_permissions=True)

		token = self.instance.get_password("cargo_access_token")
		self.assertEqual(claims_of(token)["instance"], self.instance.name)

	def test_a_host_keeps_the_token_it_was_issued(self):
		"""A fresh token is a re-registration, not a side effect of any other save."""
		self.instance.status = "Registered"
		self.instance.save(ignore_permissions=True)
		issued = self.instance.get_password("cargo_access_token")

		self.instance.base_url = "http://cargo.test:8000"
		self.instance.save(ignore_permissions=True)

		self.assertEqual(self.instance.get_password("cargo_access_token"), issued)

	def test_a_host_that_is_not_registered_gets_none(self):
		self.instance.base_url = "http://cargo.test:8000"
		self.instance.save(ignore_permissions=True)

		self.assertIsNone(self.instance.get_password("cargo_access_token", raise_exception=False))
