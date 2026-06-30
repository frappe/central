from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from central.central.doctype.team_invitation.team_invitation import expire_pending_invitations
from central.iam import can, get_fc_teams_claim


def create_user(email: str) -> str:
	if frappe.db.exists("User", email):
		return email

	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@", 1)[0],
			"enabled": 1,
			"send_welcome_email": 0,
		}
	).insert()
	return email


class TestTeamManagement(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = create_user("team.owner@example.test")
		self.admin = create_user("team.admin@example.test")
		self.viewer = create_user("team.viewer@example.test")
		self.invitee = create_user("team.invitee@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Managed Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.admin, "role": "Admin", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_invites_existing_user_and_user_accepts(self):
		frappe.set_user(self.owner)
		invitation_name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Developer")

		frappe.set_user(self.invitee)
		result = frappe.get_doc("Team Invitation", invitation_name).accept()

		self.assertTrue(result["accepted"])
		self.assertTrue(can(self.invitee, self.team.name, "server:create"))
		self.assertIn(self.team.name, get_fc_teams_claim(self.invitee))

		invitation = frappe.get_doc("Team Invitation", invitation_name)
		self.assertEqual(invitation.status, "Accepted")
		self.assertEqual(invitation.accepted_by, self.invitee)

	def test_invitation_uses_email_template(self):
		frappe.set_user(self.owner)

		with patch("central.central.doctype.team_invitation.team_invitation.frappe.sendmail") as sendmail:
			invitation_name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Developer")

		message = sendmail.call_args.kwargs["message"]
		self.assertIn("Join Managed Team", message)
		self.assertIn("Developer", message)
		self.assertIn(f"/app/team-invitation/{invitation_name}", message)
		self.assertIn("View invitation", message)

	def test_admin_can_invite_but_viewer_cannot(self):
		frappe.set_user(self.admin)
		invitation_name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Viewer")
		self.assertTrue(frappe.db.exists("Team Invitation", invitation_name))

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Team", self.team.name).invite_member("blocked@example.test", "Viewer")

	def test_duplicate_and_owner_invitations_are_rejected(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		team.invite_member(self.invitee, "Viewer")

		with self.assertRaises(frappe.ValidationError):
			team.invite_member(self.invitee, "Developer")
		with self.assertRaises(frappe.ValidationError):
			team.invite_member("new.owner@example.test", "Owner")

	def test_expired_invitation_cannot_be_accepted(self):
		frappe.set_user(self.owner)
		name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Viewer")

		frappe.set_user("Administrator")
		invitation = frappe.get_doc("Team Invitation", name)
		invitation.expires_on = add_days(today(), -1)
		invitation.save()

		frappe.set_user(self.invitee)
		with self.assertRaises(frappe.ValidationError):
			invitation.accept()

		frappe.set_user("Administrator")
		expire_pending_invitations()
		invitation.reload()
		self.assertEqual(invitation.status, "Expired")

	def test_invitee_cannot_edit_invitation_fields_directly(self):
		frappe.set_user(self.owner)
		name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Viewer")

		frappe.set_user(self.invitee)
		invitation = frappe.get_doc("Team Invitation", name)
		invitation.status = "Accepted"
		with self.assertRaises(frappe.PermissionError):
			invitation.save()

	def test_new_user_automatically_accepts_pending_invitation(self):
		email = f"team.new.{frappe.generate_hash(length=8)}@example.test"
		frappe.set_user(self.owner)
		invitation_name = frappe.get_doc("Team", self.team.name).invite_member(email, "Viewer")

		frappe.set_user("Administrator")
		create_user(email)

		invitation = frappe.get_doc("Team Invitation", invitation_name)
		self.assertEqual(invitation.status, "Accepted")
		self.assertTrue(can(email, self.team.name, "server:view"))
		self.assertFalse(can(email, self.team.name, "server:terminate"))

	def test_team_changes_follow_capabilities(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		team.team_name = "Renamed Team"
		team.save()

		frappe.set_user(self.viewer)
		team = frappe.get_doc("Team", self.team.name)
		team.team_name = "Unauthorized Rename"
		with self.assertRaises(frappe.PermissionError):
			team.save()

	def test_admin_cannot_change_own_membership_or_assign_owner(self):
		frappe.set_user(self.admin)
		team = frappe.get_doc("Team", self.team.name)

		with self.assertRaises(frappe.PermissionError):
			team.set_member_role(self.admin, "Developer")
		with self.assertRaises(frappe.ValidationError):
			team.set_member_role(self.viewer, "Owner")

		team.set_member_role(self.viewer, "Developer")
		self.assertTrue(can(self.viewer, self.team.name, "server:create"))

	def test_only_owner_can_transfer_ownership(self):
		frappe.set_user(self.admin)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Team", self.team.name).transfer_ownership(self.admin)

		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		team.transfer_ownership(self.admin)

		team.reload()
		self.assertEqual(team.owner_user, self.admin)
		self.assertEqual(team._get_member(self.admin).role, "Owner")
		self.assertEqual(team._get_member(self.owner).role, "Admin")
