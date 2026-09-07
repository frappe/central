"""The Cargo token gate: a host may only act on the region its token was minted for.

Covers the region binding on `central.api.cargo`, which is what stops a valid host from
reading another region's cluster secrets, repointing its endpoints, or deactivating it.
get_request_header is patched, no live HTTP."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import cargo as cargo_api
from central.integrations import cargo as cargo_module
from central.sso import CARGO_CENTRAL_SCOPE, CARGO_TTL, _mint, mint_cargo_access_tokens
from central.tests.utils import ensure_region

OWN_REGION = "cargo-own"
OTHER_REGION = "cargo-other"


def ensure_cargo_instance(region: str, status: str = "Registered") -> str:
	"""The Cargo host for a region, with its Region master."""
	ensure_region(region)
	name = f"CARGO-{region}"
	if not frappe.db.exists("Cargo Instance", name):
		frappe.get_doc({"doctype": "Cargo Instance", "region": region}).insert(ignore_permissions=True)
	frappe.db.set_value("Cargo Instance", name, "status", status)
	return name


@contextmanager
def _token(token: str):
	values = {cargo_module.TOKEN_HEADER: token}
	with patch.object(cargo_module.frappe, "get_request_header", side_effect=lambda k: values.get(k)):
		yield


class TestCargoRegionBinding(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.own = ensure_cargo_instance(OWN_REGION)
		ensure_cargo_instance(OTHER_REGION)
		self.token = mint_cargo_access_tokens(self.own)["central_access_token"]

	def test_tokens_carry_the_host_they_were_minted_for(self):
		claims = cargo_module.verify_cargo_access_token(self.token)
		self.assertEqual(claims["instance"], self.own)

	def test_atlas_token_carries_the_host_too(self):
		"""Atlas verifies against the JWKS, so the binding has to ride the token itself."""
		tokens = mint_cargo_access_tokens(self.own)
		self.assertNotEqual(tokens["atlas_access_token"], tokens["central_access_token"])

	def test_own_region_reaches_the_handler(self):
		with (
			_token(self.token),
			patch("central.services.storage.mint_cluster_tokens", return_value={"ok": 1}) as minted,
		):
			self.assertEqual(cargo_api.garage_tokens(region=OWN_REGION), {"ok": 1})
		minted.assert_called_once_with(OWN_REGION)

	def test_another_region_cannot_read_its_secrets(self):
		with (
			_token(self.token),
			patch("central.services.storage.mint_cluster_tokens") as minted,
		):
			with self.assertRaises(frappe.PermissionError):
				cargo_api.garage_tokens(region=OTHER_REGION)
		minted.assert_not_called()

	def test_another_region_cannot_be_repointed(self):
		with (
			_token(self.token),
			patch("central.services.storage.activate_cluster") as activated,
		):
			with self.assertRaises(frappe.PermissionError):
				cargo_api.register_cluster(
					region=OTHER_REGION,
					base_url="http://attacker.test",
					s3_endpoint="http://attacker.test:3900",
				)
		activated.assert_not_called()

	def test_another_region_cannot_be_deactivated(self):
		with (
			_token(self.token),
			patch("central.services.storage.record_cluster_failure") as recorded,
		):
			with self.assertRaises(frappe.PermissionError):
				cargo_api.report_failure(region=OTHER_REGION, step="boot", error="x")
		recorded.assert_not_called()

	def test_a_missing_region_is_refused(self):
		with _token(self.token), self.assertRaises(frappe.PermissionError):
			cargo_api.garage_tokens(region="")

	def test_a_token_without_a_host_is_refused(self):
		"""Tokens minted before hosts were identified must fail closed, not match everything."""
		legacy = _mint("central", CARGO_CENTRAL_SCOPE, CARGO_TTL)
		with _token(legacy), self.assertRaises(frappe.AuthenticationError):
			cargo_api.garage_tokens(region=OWN_REGION)

	def test_a_token_naming_an_unknown_host_is_refused(self):
		ghost = _mint("central", CARGO_CENTRAL_SCOPE, CARGO_TTL, {"instance": "CARGO-nowhere"})
		with _token(ghost), self.assertRaises(frappe.AuthenticationError):
			cargo_api.garage_tokens(region=OWN_REGION)

	def test_a_disabled_host_is_refused(self):
		ensure_cargo_instance(OWN_REGION, status="Disabled")
		with _token(self.token), self.assertRaises(frappe.AuthenticationError):
			cargo_api.garage_tokens(region=OWN_REGION)

	def test_minting_without_a_host_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			mint_cargo_access_tokens("")
