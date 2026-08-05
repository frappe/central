# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from central.api.pilot import config, enroll
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.sso import jwks_url, mint_bootstrap_token
from central.tests.test_iam import ensure_user


class TestEnrollment(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("enroll.owner@example.test")
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Enroll Team",
					"owner_user": self.owner,
					"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		self.pcid = "pcred-enroll-1"
		if frappe.db.exists("Pilot Credential", self.pcid):
			frappe.delete_doc("Pilot Credential", self.pcid, force=True)

	def _token(self) -> str:
		return mint_bootstrap_token(team=self.team, pilot_credential_id=self.pcid)

	def test_enroll_returns_a_working_credential_and_discovery(self):
		result = enroll(self._token())

		# The audience id is the pilot_credential_id — Central controls it up front.
		self.assertEqual(result["audience_id"], self.pcid)
		self.assertEqual(result["jwks_url"], jwks_url())
		# The returned token authenticates as this pilot, bound to the team + audience.
		credential = PilotCredential.verify(result["auth_token"])
		self.assertIsNotNone(credential)
		self.assertEqual(credential.team, self.team)
		self.assertEqual(credential.audience_id, self.pcid)

	def test_bootstrap_token_is_single_use(self):
		token = self._token()
		enroll(token)
		with self.assertRaises(frappe.AuthenticationError):
			enroll(token)

	def test_a_non_enrollment_token_is_rejected(self):
		from central.sso import mint_bench_login

		with self.assertRaises(frappe.AuthenticationError):
			enroll(mint_bench_login(self.pcid))

	def test_garbage_token_is_rejected(self):
		with self.assertRaises(frappe.AuthenticationError):
			enroll("not-a-jwt")

	def test_config_reports_this_pilots_audience(self):
		token = enroll(self._token())["auth_token"]
		set_request(
			method="GET", path="/api/method/central.api.pilot.config", headers={"X-Pilot-Token": token}
		)
		result = config()
		self.assertEqual(result["audience_id"], self.pcid)
		self.assertEqual(result["jwks_url"], jwks_url())
