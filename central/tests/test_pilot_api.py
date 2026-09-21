# Copyright (c) 2026, frappe and Contributors
# See license.txt

import random

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, set_request

from central.api.pilot import datum_token, heartbeat
from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import DATUM_SCOPE
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestPilotAPI(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("bench.api.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Bench API Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.token = PilotCredential.mint(team=self.team, pilot_credential_id="api-pilot-1")
		# A datum token is signed with the regional key, which an operator initializes once.
		CentralSSOSettings.instance().initialize_atlas_signing_key()

	def call_heartbeat(self, token: str | None) -> dict:
		"""Invoke the endpoint as a bench would: an X-Pilot-Token header, or none."""
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.heartbeat", headers=headers)
		return heartbeat()

	def test_valid_token_resolves_team_and_bench(self):
		result = self.call_heartbeat(self.token)
		self.assertTrue(result["ok"])
		self.assertEqual(result["team"], self.team)
		self.assertEqual(result["pilot_credential_id"], "api-pilot-1")

	def test_missing_header_is_rejected(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(None)

	def test_garbage_token_is_rejected(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat("not-a-real-token")

	def test_revoked_token_is_rejected(self):
		frappe.get_doc("Pilot Credential", "api-pilot-1").revoke()
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(self.token)

	def test_expired_token_is_rejected(self):
		bench = frappe.get_doc("Pilot Credential", "api-pilot-1")
		bench.db_set("expires_at", add_to_date(now_datetime(), hours=-1))
		with self.assertRaises(frappe.AuthenticationError):
			self.call_heartbeat(self.token)

	def bound_pilot(self, region_id: int | None = None) -> str:
		"""A pilot with an Asset in a region, which is what a datum token is addressed to.

		The region id is unique per Region, so each test gets its own rather than
		colliding with whatever the site already holds."""
		self.region = f"tel-{frappe.generate_hash(length=6)}"
		ensure_atlas_instance(self.region, atlas_region_id=str(region_id or random.randint(1, 65535)))
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": f"vm-{self.region}",
				"team": self.team,
				"cluster": self.region,
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", asset.name)

		return asset.name

	def reporting_region(self, service_endpoint: str, status: str = "Available") -> str:
		"""A bound pilot whose region has reported where its telemetry host serves."""
		self.bound_pilot()
		frappe.get_doc(
			{
				"doctype": "Service Detail",
				"region": self.region,
				"service": "telemetry",
				"status": status,
				"service_endpoint": service_endpoint,
			}
		).insert(ignore_permissions=True)

		return f"{self.region}-telemetry"

	def test_token_names_the_regional_telemetry_endpoint(self):
		"""The pilot is told where to ship without being told which region it is in: the
		Asset's cluster is the region, and that region's own report names the host."""
		self.reporting_region("https://datum.example.test")

		self.assertEqual(self.call_datum_token(self.token)["endpoint"], "https://datum.example.test")

	def test_a_region_reporting_itself_down_hands_out_no_endpoint(self):
		"""Shipping at a host that says it is down only loses the rows. The token is still
		minted -- it is the endpoint that is missing, not the pilot's right to telemetry."""
		self.reporting_region("https://datum.example.test", status="Not Available")

		result = self.call_datum_token(self.token)
		self.assertIsNone(result["endpoint"])
		self.assertTrue(result["token"])

	def test_a_region_that_has_never_reported_hands_out_no_endpoint(self):
		"""No row at all, which is where every region starts."""
		self.bound_pilot()

		self.assertIsNone(self.call_datum_token(self.token)["endpoint"])

	def test_an_unbound_pilot_gets_no_token_at_all(self):
		"""No Asset means no resource to attribute rows to, so the mint is refused before
		the region is ever resolved."""
		self.reporting_region("https://datum.example.test")
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", None)

		with self.assertRaises(frappe.ValidationError):
			self.call_datum_token(self.token)

	def call_datum_token(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.datum_token", headers=headers)
		return datum_token()

	def test_the_token_carries_the_scope_resource_and_write_access(self):
		"""Datum stamps every row with `resource_id` and reads both claims off the token
		through `Identity.from_claims`. Nothing sits in front of it to translate one."""
		asset = self.bound_pilot()

		claims = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["scope"], DATUM_SCOPE)
		self.assertEqual(claims["resource_id"], asset)
		self.assertEqual(claims["access"], ["write"])
		self.assertNotIn("vm_access", claims)

	def test_the_token_is_addressed_to_the_pilots_own_region(self):
		"""Every region reads the same key set, so the audience is what keeps a pilot
		from writing to another region's datum."""
		self.bound_pilot(region_id=7)

		claims = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["aud"], "atlas-datum:7")

	def test_the_token_is_signed_for_the_key_set_datum_reads(self):
		"""Datum fetches the merged set, which carries Ed25519 keys namespaced by issuer."""
		self.bound_pilot()

		token = self.call_datum_token(self.token)["token"]

		self.assertEqual(jwt.get_unverified_header(token)["alg"], "EdDSA")
		self.assertTrue(jwt.get_unverified_header(token)["kid"].startswith("central:"))
		self.assertEqual(jwt.decode(token, options={"verify_signature": False})["iss"], "central")

	def test_each_mint_is_its_own_credential(self):
		"""One route, but not one token: a pilot re-fetching gets a fresh credential, so
		one expiring or being replayed says nothing about the last."""
		self.bound_pilot()

		first = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})
		second = jwt.decode(self.call_datum_token(self.token)["token"], options={"verify_signature": False})

		self.assertNotEqual(first["jti"], second["jti"])
		for claim in ("iss", "sub", "aud", "scope", "resource_id", "access"):
			self.assertEqual(first[claim], second[claim])

	def test_the_token_waits_for_the_resource(self):
		"""Atlas binds the Asset after provisioning; before that the rows would carry
		no resource id."""
		with self.assertRaises(frappe.ValidationError):
			self.call_datum_token(self.token)
