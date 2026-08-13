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
