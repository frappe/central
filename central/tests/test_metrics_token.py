# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
import jwt
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request
from jwt.algorithms import RSAAlgorithm

from central.api.jwks import jwks_document
from central.api.pilot import metrics_token
from central.central.doctype.central_sso_settings.central_sso_settings import ALGORITHM
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import METRICS_SCOPE, central_url, mint_metrics_token
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

RESOURCE_ID = "vm-metrics-1"
PILOT_ID = "metrics-pilot-1"


class TestMetricsToken(IntegrationTestCase):
	"""Signature, scope and labels all have to be right, or metrics land
	unattributed."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("metrics.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Metrics Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.cluster = "blr-metrics"
		ensure_region(self.cluster)
		if not frappe.db.exists("Atlas Instance", self.cluster):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.cluster,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()
		self.token = PilotCredential.mint(team=self.team, pilot_credential_id=PILOT_ID)

	def provision(self) -> str:
		"""What Atlas does once the VM exists: create the Asset, bind it to the pilot."""
		if not frappe.db.exists("Asset", RESOURCE_ID):
			frappe.get_doc(
				{
					"doctype": "Asset",
					"resource_id": RESOURCE_ID,
					"team": self.team,
					"cluster": self.cluster,
					"status": "Running",
				}
			).insert(ignore_permissions=True)
		PilotCredential.link_asset(PILOT_ID, RESOURCE_ID)
		return RESOURCE_ID

	def verify_like_vmauth(self, token: str, audience: str) -> dict:
		"""Verify exactly as vmauth would: Central's published JWKS, nothing else."""
		public_key = RSAAlgorithm.from_jwk(jwks_document()["keys"][0])
		return jwt.decode(
			token,
			public_key,
			algorithms=[ALGORITHM],
			audience=audience,
			issuer=central_url(),
			options={"require": ["exp", "aud", "iss"]},
		)

	def call(self, token: str | None) -> dict:
		headers = {"X-Pilot-Token": token} if token is not None else {}
		set_request(method="GET", path="/api/method/central.api.pilot.metrics_token", headers=headers)
		return metrics_token()

	def test_the_token_carries_the_resource_id_as_a_label(self):
		claims = self.verify_like_vmauth(mint_metrics_token(PILOT_ID, RESOURCE_ID), PILOT_ID)

		self.assertEqual(claims["vm_access"]["metrics_extra_labels"], [f"resource_id={RESOURCE_ID}"])

	def test_the_scope_marks_it_as_a_metrics_token(self):
		"""Signed with the same key as bench logins; scope is what separates them."""
		claims = self.verify_like_vmauth(mint_metrics_token(PILOT_ID, RESOURCE_ID), PILOT_ID)

		self.assertEqual(claims["scope"], METRICS_SCOPE)

	def test_minting_without_a_resource_is_refused(self):
		"""Atlas binds the resource after provisioning; a token minted before then
		would carry no label."""
		with self.assertRaises(frappe.ValidationError):
			mint_metrics_token(PILOT_ID, "")

	def test_the_endpoint_serves_the_authenticated_pilot(self):
		self.provision()

		result = self.call(self.token)
		claims = self.verify_like_vmauth(result["token"], PILOT_ID)

		self.assertEqual(result["resource_id"], RESOURCE_ID)
		self.assertEqual(claims["vm_access"]["metrics_extra_labels"], [f"resource_id={RESOURCE_ID}"])

	def test_an_unauthenticated_caller_gets_nothing(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.call(None)

	def test_a_pilot_awaiting_provisioning_is_told_to_wait(self):
		with self.assertRaises(frappe.ValidationError):
			self.call(self.token)
