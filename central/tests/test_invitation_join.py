from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from central.api.auth import _otp_key, sign_up, sign_up_with_invitation, verify_signup
from central.api.teams import get_invitation
from central.iam import can, get_user_team_names
from central.tests.test_team_management import create_user


class TestInvitationJoin(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = create_user("join.owner@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Joining Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.email = f"join.new.{frappe.generate_hash(length=8)}@example.test"
		self.invitation = self._invite(self.email)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_token_shows_the_invitation_to_a_guest(self):
		frappe.set_user("Guest")
		summary = get_invitation(self.invitation.token)

		self.assertEqual(summary["team_name"], "Joining Team")
		self.assertEqual(summary["email"], self.email)
		self.assertEqual(summary["role"], "Developer")
		self.assertEqual(summary["status"], "Pending")
		self.assertFalse(summary["has_account"])
		self.assertNotIn("token", summary)

	def test_unknown_token_is_refused(self):
		frappe.set_user("Guest")
		for token in ("not-a-token", "", None):
			with self.assertRaises(frappe.DoesNotExistError):
				get_invitation(token)

	def test_new_invitee_joins_with_the_token_and_gets_no_personal_team(self):
		frappe.set_user("Guest")
		with patch("frappe.local.login_manager", create=True) as login_manager:
			login_manager.login_as.side_effect = frappe.set_user
			result = sign_up_with_invitation(self.invitation.token, "New Invitee")

		self.assertEqual(frappe.session.user, self.email)
		self.assertEqual(result["team"], self.team.name)
		self.assertEqual(get_user_team_names(self.email), [self.team.name])
		self.assertTrue(can(self.email, self.team.name, "server:create"))
		self.assertEqual(frappe.db.get_value("Team Invitation", self.invitation.name, "status"), "Accepted")

	def test_token_joins_only_its_own_team(self):
		other_team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Other Inviting Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		frappe.set_user(self.owner)
		with patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail"):
			other = frappe.get_doc("Team", other_team.name).invite_member(self.email, "Viewer")

		frappe.set_user("Guest")
		with patch("frappe.local.login_manager", create=True) as login_manager:
			login_manager.login_as.side_effect = frappe.set_user
			sign_up_with_invitation(self.invitation.token, "New Invitee")

		self.assertEqual(get_user_team_names(self.email), [self.team.name])
		self.assertEqual(frappe.db.get_value("Team Invitation", other, "status"), "Pending")

	def test_token_never_signs_in_an_existing_account(self):
		create_user(self.email)
		frappe.set_user("Guest")
		with patch("frappe.local.login_manager", create=True) as login_manager:
			with self.assertRaises(frappe.ValidationError):
				sign_up_with_invitation(self.invitation.token, "Someone")
			login_manager.login_as.assert_not_called()

	def test_expired_or_revoked_token_cannot_join(self):
		frappe.db.set_value("Team Invitation", self.invitation.name, "expires_on", add_days(today(), -1))
		revoked = self._invite(f"join.revoked.{frappe.generate_hash(length=8)}@example.test")
		frappe.set_user(self.owner)
		revoked.revoke()

		frappe.set_user("Guest")
		self.assertEqual(get_invitation(self.invitation.token)["status"], "Expired")
		for token in (self.invitation.token, revoked.token):
			with patch("frappe.local.login_manager", create=True):
				with self.assertRaises(frappe.ValidationError):
					sign_up_with_invitation(token, "Too Late")
		self.assertFalse(frappe.db.exists("User", self.email))

	def test_otp_signup_with_a_pending_invitation_joins_that_team(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.cache.delete_value, _otp_key(self.email))
		with patch("central.api.auth.frappe.sendmail"):
			sign_up(self.email, "Code Invitee")
		code = frappe.cache.get_value(_otp_key(self.email))["code"]

		with (
			patch("frappe.local.login_manager", create=True) as login_manager,
			patch("central.api.auth._provision_signup_billing") as provision_billing,
		):
			login_manager.login_as.side_effect = frappe.set_user
			result = verify_signup(self.email, code)

		self.assertIsNone(result["team"])
		self.assertEqual(get_user_team_names(self.email), [self.team.name])
		provision_billing.assert_not_called()

	def _invite(self, email: str):
		frappe.set_user(self.owner)
		with patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail"):
			name = frappe.get_doc("Team", self.team.name).invite_member(email, "Developer")
		frappe.set_user("Administrator")
		return frappe.get_doc("Team Invitation", name)
