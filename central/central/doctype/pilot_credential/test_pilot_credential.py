# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.central.doctype.pilot_credential.pilot_credential import TOKEN_LENGTH, PilotCredential
from central.tests.test_iam import ensure_user


class IntegrationTestPilotCredential(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("bench.cred.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Pilot Credential Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert().name

	def mint(self, pilot_credential_id: str = "pilot-1", **kwargs) -> str:
		return PilotCredential.mint(team=self.team, pilot_credential_id=pilot_credential_id, **kwargs)

	def test_mint_returns_plaintext_and_stores_only_hash(self):
		token = self.mint()
		doc = frappe.get_doc("Pilot Credential", "pilot-1")
		self.assertEqual(len(token), TOKEN_LENGTH)
		self.assertEqual(doc.team, self.team)
		self.assertEqual(doc.status, "Active")
		self.assertNotEqual(doc.token_hash, token)
		self.assertEqual(doc.token_hash, PilotCredential._hash(token))

	def test_verify_resolves_and_stamps_last_used(self):
		token = self.mint()
		doc = PilotCredential.verify(token)
		self.assertIsNotNone(doc)
		self.assertEqual(doc.pilot_credential_id, "pilot-1")
		self.assertEqual(doc.team, self.team)
		self.assertIsNotNone(frappe.db.get_value("Pilot Credential", "pilot-1", "last_used_at"))

	def test_verify_rejects_unknown_and_empty_token(self):
		self.mint()
		self.assertIsNone(PilotCredential.verify("not-a-real-token"))
		self.assertIsNone(PilotCredential.verify(""))

	def test_revoke_blocks_verify(self):
		token = self.mint()
		frappe.get_doc("Pilot Credential", "pilot-1").revoke()
		self.assertEqual(frappe.db.get_value("Pilot Credential", "pilot-1", "status"), "Revoked")
		self.assertIsNone(PilotCredential.verify(token))

	def test_expired_credential_blocks_verify(self):
		token = self.mint(expires_at=add_to_date(now_datetime(), hours=-1))
		self.assertIsNone(PilotCredential.verify(token))

	def test_rotate_invalidates_old_token(self):
		old = self.mint()
		new = frappe.get_doc("Pilot Credential", "pilot-1").rotate()
		self.assertNotEqual(old, new)
		self.assertIsNone(PilotCredential.verify(old))
		self.assertIsNotNone(PilotCredential.verify(new))

	def test_mint_is_idempotent_per_bench(self):
		old = self.mint()
		new = self.mint()  # same pilot_credential_id
		self.assertEqual(frappe.db.count("Pilot Credential", {"pilot_credential_id": "pilot-1"}), 1)
		self.assertIsNone(PilotCredential.verify(old))
		self.assertIsNotNone(PilotCredential.verify(new))

	def test_revoke_by_id_blocks_verify(self):
		token = self.mint()
		PilotCredential.revoke_by_id("pilot-1")
		self.assertEqual(frappe.db.get_value("Pilot Credential", "pilot-1", "status"), "Revoked")
		self.assertIsNone(PilotCredential.verify(token))

	def test_revoke_by_id_unknown_is_noop(self):
		PilotCredential.revoke_by_id("does-not-exist")  # must not raise
		PilotCredential.revoke_by_id(None)

	def test_link_asset_binds_and_is_noop_without_ids(self):
		self.mint()
		PilotCredential.link_asset("pilot-1", "vm-resource-1")
		self.assertEqual(frappe.db.get_value("Pilot Credential", "pilot-1", "asset"), "vm-resource-1")
		PilotCredential.link_asset("pilot-1", None)  # no-op, keeps prior link
		self.assertEqual(frappe.db.get_value("Pilot Credential", "pilot-1", "asset"), "vm-resource-1")

	def test_rotate_by_id_issues_new_working_token(self):
		old = self.mint()
		new = PilotCredential.rotate_by_id("pilot-1")
		self.assertIsNone(PilotCredential.verify(old))
		self.assertIsNotNone(PilotCredential.verify(new))

	def test_verify_rejects_token_rotated_between_lookup_and_load(self):
		"""TOCTOU guard: if the row rotates to a new token between the hash lookup and the
		doc load, the superseded token is rejected — not admitted one extra time."""
		old = self.mint()
		frappe.get_doc("Pilot Credential", "pilot-1").rotate()  # row now holds a new hash
		# Force the lookup to resolve the name as if it matched before the rotate committed;
		# the post-load hash re-check must still reject the old token.
		with patch("frappe.db.get_value", return_value="pilot-1"):
			self.assertIsNone(PilotCredential.verify(old))
