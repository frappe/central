# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.atlas import AtlasClient, _on_vm, _on_vm_deleted
from central.tests.test_iam import ensure_user

_CREDENTIAL_KEYS = {"pilot_credential_id", "central_endpoint", "central_auth_token"}


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
		self.region = "blr-delivery"
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
		# create_site commits the credential before handing it to Atlas (durability). Stub
		# the commit so it can't break test isolation, and so we can assert it fires.
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

	def test_create_site_emits_credential_params(self):
		params = self.create_site_capturing_params()
		self.assertLessEqual(_CREDENTIAL_KEYS, set(params))
		self.assertTrue(params["pilot_credential_id"].startswith("pcred-"))
		self.assertEqual(params["central_endpoint"], frappe.utils.get_url())

	def test_emitted_token_is_a_working_active_credential(self):
		params = self.create_site_capturing_params()
		self.assertEqual(frappe.db.get_value("Pilot Credential", params["pilot_credential_id"], "status"), "Active")
		credential = PilotCredential.verify(params["central_auth_token"])
		self.assertIsNotNone(credential)
		self.assertEqual(credential.team, self.team)

	def test_token_is_not_returned_to_central_caller(self):
		"""The plaintext token must reach Atlas only — never the Central API response."""
		transport = MagicMock()
		transport.post_api.return_value = {"name": "acme.blr.test", "status": "Pending", "team": self.team}
		with patch.object(AtlasClient, "client", return_value=transport):
			result = AtlasClient.for_region(self.region).create_site(team=self.team, subdomain="acme")
		self.assertNotIn("central_auth_token", result)

	def test_credential_is_committed_before_the_atlas_call(self):
		"""Durability: the credential is committed BEFORE the token is handed to Atlas, so a
		rollback of the enclosing request can't strand the bench with an unverifiable token."""
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

	def test_vm_created_event_links_credential_to_its_asset(self):
		"""Once Atlas echoes pilot_credential_id on the VM event, the credential binds to
		the Asset (VM) it runs on."""
		pcid = self.create_site_capturing_params()["pilot_credential_id"]
		payload = {"name": "vm-link-1", "team": self.team, "pilot_credential_id": pcid, "status": "Running"}
		_on_vm(self.region, payload, now_datetime())
		self.assertEqual(frappe.db.get_value("Pilot Credential", pcid, "asset"), "vm-link-1")

	def test_vm_deleted_event_revokes_credential(self):
		"""The pilot dies with its VM — vm.deleted revokes the credential, so a leaked
		token is inert."""
		params = self.create_site_capturing_params()
		pcid, token = params["pilot_credential_id"], params["central_auth_token"]
		self.assertIsNotNone(PilotCredential.verify(token))
		_on_vm_deleted(self.region, {"name": "vm-del-1", "pilot_credential_id": pcid}, now_datetime())
		self.assertEqual(frappe.db.get_value("Pilot Credential", pcid, "status"), "Revoked")
		self.assertIsNone(PilotCredential.verify(token))
