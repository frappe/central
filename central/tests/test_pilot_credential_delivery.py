# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from central.api.pilot import enroll
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.atlas import AtlasClient, _on_vm, _on_vm_deleted
from central.sso import verify_bootstrap_token
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region

# What create_site now hands Atlas to seed on the bench: the endpoint + a single-use
# bootstrap token. The long-lived auth_token is NOT here — the pilot mints it at enrollment.
_SEED_KEYS = {"pilot_credential_id", "central_endpoint", "bootstrap_token"}


class TestPilotCredentialDelivery(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("delivery.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Delivery Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert().name
		self.region = ensure_region("blr-delivery")
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()
		# create_site commits before handing off to Atlas (durability — the lazily-generated
		# signing key). Stub the commit so it can't break test isolation, and so we can assert it fires.
		commit = patch("frappe.db.commit")
		self.mock_commit = commit.start()
		self.addCleanup(commit.stop)

	def create_site_capturing_params(self) -> dict:
		"""Run AtlasClient.create_site with a stubbed transport; return the outbound params."""
		transport = MagicMock()
		transport.post_api.return_value = {"name": "acme.blr.test", "status": "Pending", "team": self.team}
		with patch.object(AtlasClient, "client", return_value=transport):
			AtlasClient.for_region(self.region).create_site(team=self.team, subdomain="acme")
		return transport.post_api.call_args.kwargs["params"]

	def test_create_site_emits_bootstrap_seed(self):
		params = self.create_site_capturing_params()
		self.assertLessEqual(_SEED_KEYS, set(params))
		self.assertNotIn("central_auth_token", params)  # the durable secret is never injected
		self.assertTrue(params["pilot_credential_id"].startswith("pcred-"))
		self.assertEqual(params["central_endpoint"], frappe.utils.get_url())

	def test_credential_is_reserved_without_a_token(self):
		"""The row exists after create_site so the vm.* events can bind it, but carries no
		token yet — so nothing can authenticate as this pilot until it enrols."""
		pcid = self.create_site_capturing_params()["pilot_credential_id"]
		self.assertEqual(frappe.db.get_value("Pilot Credential", pcid, "status"), "Active")
		self.assertFalse(frappe.db.get_value("Pilot Credential", pcid, "token_hash"))

	def test_bootstrap_token_is_a_valid_enrollment_grant(self):
		params = self.create_site_capturing_params()
		grant = verify_bootstrap_token(params["bootstrap_token"])
		self.assertEqual(grant["team"], self.team)
		self.assertEqual(grant["pcid"], params["pilot_credential_id"])

	def test_enrolling_the_seed_yields_a_working_credential(self):
		params = self.create_site_capturing_params()
		result = enroll(params["bootstrap_token"])
		credential = PilotCredential.verify(result["auth_token"])
		self.assertIsNotNone(credential)
		self.assertEqual(credential.team, self.team)
		self.assertEqual(credential.audience_id, params["pilot_credential_id"])

	def test_seed_is_not_returned_to_central_caller(self):
		"""The bootstrap token must reach Atlas only — never the Central API response."""
		transport = MagicMock()
		transport.post_api.return_value = {"name": "acme.blr.test", "status": "Pending", "team": self.team}
		with patch.object(AtlasClient, "client", return_value=transport):
			result = AtlasClient.for_region(self.region).create_site(team=self.team, subdomain="acme")
		self.assertNotIn("bootstrap_token", result)

	def test_commit_fires_before_the_atlas_call(self):
		"""Durability: the (lazily-generated) signing key is committed BEFORE the token is
		handed to Atlas, so a rollback can't discard a key the bench boots with a token from."""
		order: list[str] = []
		self.mock_commit.side_effect = lambda: order.append("commit")
		transport = MagicMock()
		transport.post_api.side_effect = lambda *a, **k: order.append("post_api") or {
			"name": "acme.blr.test",
			"status": "Pending",
			"team": self.team,
		}
		with patch.object(AtlasClient, "client", return_value=transport):
			AtlasClient.for_region(self.region).create_site(team=self.team, subdomain="acme")
		self.assertEqual(order, ["commit", "post_api"])

	def test_vm_created_event_links_reserved_credential_to_its_asset(self):
		"""The reserved credential binds to its Asset on the vm event — even before the pilot
		enrols — so billing can resolve the bench's server straight away."""
		pcid = self.create_site_capturing_params()["pilot_credential_id"]
		payload = {"name": "vm-link-1", "team": self.team, "pilot_credential_id": pcid, "status": "Running"}
		_on_vm(self.region, payload, now_datetime())
		self.assertEqual(frappe.db.get_value("Pilot Credential", pcid, "asset"), "vm-link-1")

	def test_vm_deleted_event_revokes_credential(self):
		"""The pilot dies with its VM — vm.deleted revokes the credential, so an enrolled
		token is inert afterwards."""
		params = self.create_site_capturing_params()
		pcid = params["pilot_credential_id"]
		token = enroll(params["bootstrap_token"])["auth_token"]
		self.assertIsNotNone(PilotCredential.verify(token))
		_on_vm_deleted(self.region, {"name": "vm-del-1", "pilot_credential_id": pcid}, now_datetime())
		self.assertEqual(frappe.db.get_value("Pilot Credential", pcid, "status"), "Revoked")
		self.assertIsNone(PilotCredential.verify(token))
