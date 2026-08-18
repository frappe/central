# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.catalog.entitlements import issue_token, recompute_trust_tier
from central.billing.catalog.signing import generate_keypair, verify_payload
from central.billing.tests.test_entitlements import make_ladder
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import clear_team_tier, complete_billing_profile, ensure_team


class TestIssueToken(IntegrationTestCase):
	def setUp(self):
		make_ladder()
		ensure_team("team-token")
		# Pin the currency to INR up front, as the real signup flow does. t1/t2 are
		# priced only in INR, so without this recompute would auto-create the profile in
		# the site's default currency (USD here) and the t1 cap would resolve to 0.
		complete_billing_profile("team-token", currency="INR")
		clear_team_tier("team-token")
		# Central holds the private key; the public key goes to the cluster.
		self.private_key, self.public_key = generate_keypair()
		frappe.conf.entitlement_private_key = self.private_key
		recompute_trust_tier("team-token", paid_invoice_count=3, cumulative_paid=300)  # t1, $300

	def test_issued_token_is_signed_and_verifiable_offline(self):
		result = issue_token("team-token", cluster_slices={"ap-south-1": {"max_spend": 300}})

		# Verifiable with only the public key (offline, no Central call).
		self.assertTrue(verify_payload(result["payload"], result["signature"], self.public_key))
		# Tampering with the cap breaks verification.
		tampered = {**result["payload"], "cluster_slices": {"ap-south-1": {"max_spend": 9999}}}
		self.assertFalse(verify_payload(tampered, result["signature"], self.public_key))

	def test_token_is_short_lived(self):
		result = issue_token("team-token", cluster_slices={"ap-south-1": {"max_spend": 300}})
		issued = frappe.utils.get_datetime(result["payload"]["issued_at"])
		expires = frappe.utils.get_datetime(result["payload"]["expires_at"])
		hours = (expires - issued).total_seconds() / 3600
		self.assertGreaterEqual(hours, 1)
		self.assertLessEqual(hours, 48)

	def test_cluster_slices_must_not_exceed_team_cap(self):
		with self.assertRaises(frappe.ValidationError):
			issue_token(
				"team-token",
				cluster_slices={"ap-south-1": {"max_spend": 200}, "us-east-1": {"max_spend": 200}},
			)  # 400 > team cap 300

	def test_token_carries_structured_cap(self):
		result = issue_token("team-token", cluster_slices={"ap-south-1": {"max_spend": 300}})
		payload = result["payload"]
		self.assertEqual(payload["team"], "team-token")
		self.assertIn("cluster_slices", payload)
		self.assertIn("allowed_plans", payload)
		self.assertIn("allowed_resource_types", payload)
		self.assertEqual(payload["suspend"], 0)
