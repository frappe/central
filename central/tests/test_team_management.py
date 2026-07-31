from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from central.api.identity import my_invitations
from central.api.teams import (
	create_custom_role,
	create_team,
	delete_custom_role,
	delete_team,
	decline_invitation,
	invite_team_member,
	list_team_invitations,
	rename_team,
	resend_invitation,
	revoke_invitation,
	set_team_member_roles,
	transfer_team_ownership,
)
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
		self.assertIn(f"/dashboard/invitations/{invitation_name}", message)
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
			team.set_member_roles(self.admin, [{"role": "Developer", "resource_type": "*"}])
		with self.assertRaises(frappe.ValidationError):
			team.set_member_roles(self.viewer, [{"role": "Owner", "resource_type": "*"}])

		team.set_member_roles(self.viewer, [{"role": "Developer", "resource_type": "*"}])
		self.assertTrue(can(self.viewer, self.team.name, "server:create"))

	def test_member_can_hold_multiple_roles_with_unioned_capabilities(self):
		# Proves the IAM engine needed no changes: resolve_user_grants already
		# keys grants by (team, role) and unions capabilities across every
		# Team Member row a user holds, so adding a second role grant is enough.
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		billing_only = create_custom_role(self.team.name, "Billing Only", ["server:view"])["role"]

		team.set_member_roles(
			self.viewer,
			[
				{"role": billing_only, "resource_type": "*"},
				{"role": "Developer", "resource_type": "Server", "resource_name": "some-server"},
			],
		)

		self.assertTrue(can(self.viewer, self.team.name, "server:view"))
		self.assertTrue(can(self.viewer, self.team.name, "server:create"))

	def test_duplicate_role_resource_grant_is_rejected(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)

		with self.assertRaises(frappe.ValidationError):
			team.set_member_roles(
				self.viewer,
				[
					{"role": "Developer", "resource_type": "*"},
					{"role": "Developer", "resource_type": "*"},
				],
			)

	def test_member_must_keep_at_least_one_role(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)

		with self.assertRaises(frappe.ValidationError):
			team.set_member_roles(self.viewer, [])

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

	# --- API endpoints (central.api.teams / central.api.identity) ----------------

	def test_create_team_makes_caller_the_owner(self):
		frappe.set_user(self.owner)
		result = create_team("Fresh Team")

		team = frappe.get_doc("Team", result["name"])
		self.assertEqual(team.owner_user, self.owner)
		self.assertEqual(team._get_member(self.owner).role, "Owner")
		self.assertTrue(can(self.owner, team.name, "team:delete"))

	def test_list_team_invitations_is_manager_only(self):
		frappe.set_user(self.owner)
		invite_team_member(self.team.name, self.invitee, "Developer")

		rows = list_team_invitations(self.team.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["email"], self.invitee)
		self.assertEqual(rows[0]["status"], "Pending")

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			list_team_invitations(self.team.name)

	def test_resend_invitation_extends_expiry_and_re_emails(self):
		frappe.set_user(self.owner)
		name = invite_team_member(self.team.name, self.invitee, "Developer")
		frappe.db.set_value("Team Invitation", name, "expires_on", add_days(today(), 1))

		with patch("central.central.doctype.team_invitation.team_invitation.frappe.sendmail") as sendmail:
			result = resend_invitation(name)

		sendmail.assert_called_once()
		self.assertEqual(str(result["expires_on"]), add_days(today(), 7))

	def test_revoke_invitation_blocks_further_acceptance(self):
		frappe.set_user(self.owner)
		name = invite_team_member(self.team.name, self.invitee, "Developer")

		self.assertTrue(revoke_invitation(name)["revoked"])
		self.assertEqual(frappe.db.get_value("Team Invitation", name, "status"), "Revoked")

		frappe.set_user(self.invitee)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Team Invitation", name).accept()

	def test_invitee_declines_but_others_cannot(self):
		frappe.set_user(self.owner)
		name = invite_team_member(self.team.name, self.invitee, "Developer")

		frappe.set_user(self.admin)
		with self.assertRaises(frappe.PermissionError):
			decline_invitation(name)

		frappe.set_user(self.invitee)
		self.assertTrue(decline_invitation(name)["declined"])
		self.assertEqual(frappe.db.get_value("Team Invitation", name, "status"), "Declined")
		self.assertFalse(can(self.invitee, self.team.name, "server:view"))

	def test_my_invitations_lists_pending_for_the_signed_in_user(self):
		frappe.set_user(self.owner)
		invite_team_member(self.team.name, self.invitee, "Developer")

		frappe.set_user(self.invitee)
		rows = my_invitations()

		mine = next(r for r in rows if r["team"] == self.team.name)
		self.assertEqual(mine["team_name"], "Managed Team")
		self.assertEqual(mine["role"], "Developer")
		self.assertTrue(all(r["status"] != "Accepted" for r in rows if "status" in r))

	def test_delete_custom_role_guards_system_and_in_use_roles(self):
		frappe.set_user(self.owner)
		role = create_custom_role(self.team.name, "Snapshotter", ["server:snapshot"])["role"]

		# A system role can never be deleted.
		with self.assertRaises(frappe.ValidationError):
			delete_custom_role("Viewer")

		# In use by a member -> refused until reassigned.
		set_team_member_roles(self.team.name, self.viewer, [{"role": role, "resource_type": "*"}])
		with self.assertRaises(frappe.ValidationError):
			delete_custom_role(role)

		set_team_member_roles(self.team.name, self.viewer, [{"role": "Viewer", "resource_type": "*"}])
		self.assertTrue(delete_custom_role(role)["deleted"])
		self.assertFalse(frappe.db.exists("Team Role", role))

	def test_rename_team_needs_team_edit(self):
		frappe.set_user(self.admin)
		result = rename_team(self.team.name, "Renamed via API")
		self.assertEqual(result["team_name"], "Renamed via API")

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			rename_team(self.team.name, "Viewer Rename")

	def test_transfer_team_ownership_via_api_is_owner_only(self):
		frappe.set_user(self.admin)
		with self.assertRaises(frappe.PermissionError):
			transfer_team_ownership(self.team.name, self.admin)

		frappe.set_user(self.invitee)
		with self.assertRaises(frappe.PermissionError):
			transfer_team_ownership(self.team.name, self.admin)

		frappe.set_user(self.owner)
		transfer_team_ownership(self.team.name, self.admin)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "owner_user"), self.admin)

	def test_delete_team_is_owner_only(self):
		frappe.set_user(self.owner)
		fresh = create_team("Disposable Team")["name"]

		frappe.set_user(self.admin)
		with self.assertRaises(frappe.PermissionError):
			delete_team(fresh)

		frappe.set_user(self.owner)
		self.assertTrue(delete_team(fresh)["deleted"])
		self.assertFalse(frappe.db.exists("Team", fresh))

	def test_delete_team_clears_invitations_that_would_block_it(self):
		# An invitation Links to the Team; without cleanup the delete raised
		# LinkExistsError. delete_team clears invitations + custom roles first.
		frappe.set_user(self.owner)
		team = create_team("Team With Invite")["name"]
		invite = invite_team_member(team, "blocks.delete@example.test", "Viewer")

		self.assertTrue(delete_team(team)["deleted"])
		self.assertFalse(frappe.db.exists("Team", team))
		self.assertFalse(frappe.db.exists("Team Invitation", invite))
