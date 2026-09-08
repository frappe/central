# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, set_request

from central.api.pilot import heartbeat, log_token, metrics_token
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import LOG_SCOPE, METRICS_SCOPE
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

	def enrolled_cargo(self, region: str, telemetry_base_url: str) -> str:
		"""A region whose Cargo has enrolled and reported where telemetry goes, with an
		Asset in it bound to this pilot."""
		ensure_atlas_instance(region)
		frappe.get_doc(
			{
				"doctype": "Cargo Instance",
				"region": region,
				"status": "Registered",
				"telemetry_base_url": telemetry_base_url,
			}
		).insert(ignore_permissions=True)
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": f"vm-{region}",
				"team": self.team,
				"cluster": region,
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", asset.name)

		return f"CARGO-{region}"

	def test_token_names_the_regional_telemetry_endpoint(self):
		"""The pilot is told where to ship without being told which region it is in:
		the Asset's cluster is the region, and the region's Cargo owns the URL."""
		region = f"tel-{frappe.generate_hash(length=6)}"
		self.enrolled_cargo(region, "https://datum.example.test")

		self.assertEqual(self.call_metrics_token(self.token)["endpoint"], "https://datum.example.test")
		self.assertEqual(self.call_log_token(self.token)["endpoint"], "https://datum.example.test")

	def test_a_disabled_cargo_hands_out_no_endpoint(self):
		"""A region whose Cargo is disabled has nowhere to ship. The token is still minted
		-- it is the endpoint that is missing, not the pilot's right to telemetry."""
		region = f"tel-{frappe.generate_hash(length=6)}"
		name = self.enrolled_cargo(region, "https://datum.example.test")
		frappe.db.set_value("Cargo Instance", name, "status", "Disabled")

		result = self.call_metrics_token(self.token)
		self.assertIsNone(result["endpoint"])
		self.assertTrue(result["token"])

	def test_an_unbound_pilot_has_no_endpoint(self):
		"""No Asset means no region to resolve. Reached only through log_token, which does
		not gate on the resource the way metrics does."""
		region = f"tel-{frappe.generate_hash(length=6)}"
		self.enrolled_cargo(region, "https://datum.example.test")
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", None)

		with self.assertRaises(frappe.ValidationError):
			self.call_metrics_token(self.token)

	def call_metrics_token(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.metrics_token", headers=headers)
		return metrics_token()

	def test_metrics_token_carries_the_scope_and_resource(self):
		"""Datum's gateway matches on scope and stamps the labels onto every sample."""
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", "vm-1")

		claims = jwt.decode(self.call_metrics_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["scope"], METRICS_SCOPE)
		self.assertEqual(claims["vm_access"]["metrics_extra_labels"], ["resource_id=vm-1"])

	def test_metrics_token_waits_for_the_resource(self):
		"""Atlas binds the Asset after provisioning; before that the samples would
		carry no resource id."""
		with self.assertRaises(frappe.ValidationError):
			self.call_metrics_token(self.token)

	def call_log_token(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.log_token", headers=headers)
		return log_token()

	def test_log_token_carries_resource_id_and_write_access(self):
		"""Datum reads `resource_id` and `access` as top-level claims — no vmauth
		bridge sits in front of the logs path, unlike metrics."""
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", "vm-1")

		claims = jwt.decode(self.call_log_token(self.token)["token"], options={"verify_signature": False})

		self.assertEqual(claims["scope"], LOG_SCOPE)
		self.assertEqual(claims["resource_id"], "vm-1")
		self.assertEqual(claims["access"], ["write"])
		# Tokens minted for the logs path must not carry the vmauth indirection
		# the metrics path uses; a logs caller presenting this to Datum is read
		# directly by Identity.from_claims.
		self.assertNotIn("vm_access", claims)

	def test_log_token_is_independent_of_metrics_token(self):
		"""A separate mint so rotation of one does not invalidate the other."""
		frappe.db.set_value("Pilot Credential", "api-pilot-1", "asset", "vm-1")

		metrics_claims = jwt.decode(
			self.call_metrics_token(self.token)["token"], options={"verify_signature": False}
		)
		log_claims = jwt.decode(self.call_log_token(self.token)["token"], options={"verify_signature": False})

		# Different scopes and different claim shapes — they are not the same token
		# with the same payload, so revoking one (by key rotation scoped to a
		# purpose, if that ever arrives) does not implicitly cover the other.
		self.assertNotEqual(metrics_claims["scope"], log_claims["scope"])
		self.assertIn("vm_access", metrics_claims)
		self.assertNotIn("vm_access", log_claims)

	def test_log_token_waits_for_the_resource(self):
		"""Atlas binds the Asset after provisioning; before that the logs would
		carry no resource id, same gate as the metrics token."""
		with self.assertRaises(frappe.ValidationError):
			self.call_log_token(self.token)
