from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from central.api.identity import my_invitations, my_teams
from central.api.teams import (
	create_custom_role,
	create_team,
	decline_invitation,
	delete_custom_role,
	delete_team,
	invite_team_member,
	leave_team,
	rename_team,
	resend_invitation,
	revoke_invitation,
	set_team_logo,
	set_team_member_roles,
	transfer_team_ownership,
)
from central.iam import can, get_user_team_names, resolve_user_grants
from central.identity.doctype.team_invitation.team_invitation import expire_pending_invitations
from central.tests.utils import ensure_server, upload_test_image


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


def _ensure_event_type(event_type, **overrides):
	frappe.db.delete("Notification Event Type", {"event_type": event_type})
	defaults = {
		"doctype": "Notification Event Type",
		"event_type": event_type,
		"category": "Team",
		"severity": "Info",
		"required_cap": "team:manage_members",
		"in_app_title": "Notification",
		"in_app_body": "{{ message }}",
		"direct_recipients": "None",
		"create_in_app": 0,
	}
	defaults.update(overrides)
	return frappe.get_doc(defaults).insert(ignore_permissions=True)


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

		# Test sites have no outgoing email account.
		sendmail = patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail")
		sendmail.start()
		self.addCleanup(sendmail.stop)
		_ensure_event_type("role_change", direct_recipients="Affected User")
		_ensure_event_type("member_joined")
		self.server = ensure_server("srv-x", self.team.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_wildcard_grant_absorbs_same_role_resource_grants(self):
		# "Developer on everything" plus "Developer on one server" is
		# contradictory — the save keeps the wildcard and drops its shadow.
		frappe.set_user(self.owner)
		frappe.get_doc("Team", self.team.name).set_member_roles(
			self.viewer,
			[
				{"role": "Developer", "resource_type": "*", "resource_name": None},
				{"role": "Developer", "resource_type": "Server", "resource_name": "srv-x"},
				{"role": "Billing", "resource_type": "Server", "resource_name": "srv-x"},
			],
		)

		grants = [
			(row.role, row.resource_type, row.resource_name or None)
			for row in frappe.get_doc("Team", self.team.name).members
			if row.user == self.viewer
		]
		self.assertIn(("Developer", "*", None), grants)
		self.assertNotIn(("Developer", "Server", "srv-x"), grants)
		# A different role scoped to the same resource is a real grant — kept.
		self.assertIn(("Billing", "Server", "srv-x"), grants)

	def test_shadowed_rows_do_not_block_a_metadata_only_save(self):
		# A stored team can already hold a wildcard and its shadow — rows written
		# before this rule existed. Normalizing them away on save is not a member
		# edit, so someone holding only team:edit must still be able to rename.
		frappe.set_user(self.owner)
		editor = create_custom_role(self.team.name, "Editor Only", ["team:edit"])["role"]
		frappe.get_doc("Team", self.team.name).set_member_roles(
			self.viewer, [{"role": editor, "resource_type": "*"}]
		)

		# Written straight to the table: a normal save would absorb it on the way in.
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": "Team Member",
				"parenttype": "Team",
				"parentfield": "members",
				"parent": self.team.name,
				"user": self.viewer,
				"status": "Active",
				"role": editor,
				"resource_type": "Server",
				"resource_name": "srv-x",
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.viewer)  # holds team:edit, not team:manage_members
		team = frappe.get_doc("Team", self.team.name)
		team.team_name = "Renamed Team"
		team.save()

		saved = frappe.get_doc("Team", self.team.name)
		grants = [
			(row.role, row.resource_type, row.resource_name or None)
			for row in saved.members
			if row.user == self.viewer
		]
		self.assertEqual(saved.team_name, "Renamed Team")
		self.assertIn((editor, "*", None), grants)
		self.assertNotIn((editor, "Server", "srv-x"), grants)

	def test_owner_invites_existing_user_and_user_accepts(self):
		frappe.set_user(self.owner)
		invitation_name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Developer")

		frappe.set_user(self.invitee)
		result = frappe.get_doc("Team Invitation", invitation_name).accept()

		self.assertTrue(result["accepted"])
		self.assertTrue(can(self.invitee, self.team.name, "server:create"))
		self.assertIn(self.team.name, resolve_user_grants(self.invitee))

		invitation = frappe.get_doc("Team Invitation", invitation_name)
		self.assertEqual(invitation.status, "Accepted")
		self.assertEqual(invitation.accepted_by, self.invitee)

	def test_invitation_email_links_the_join_page(self):
		frappe.set_user(self.owner)

		with patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail") as sendmail:
			invitation_name = frappe.get_doc("Team", self.team.name).invite_member(self.invitee, "Developer")

		token = frappe.db.get_value("Team Invitation", invitation_name, "token")
		email = sendmail.call_args.kwargs
		self.assertEqual(email["recipients"], [self.invitee])
		self.assertEqual(email["template"], "team_invitation")
		self.assertIn("Managed Team", email["subject"])
		self.assertEqual(email["args"]["role"], "Developer")
		self.assertTrue(email["args"]["invitation_url"].endswith(f"/dashboard/join/{token}"))

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

	def test_new_user_with_a_pending_invitation_gets_no_personal_team(self):
		# Creating the user accepts nothing: the signup that created them decides.
		email = f"team.new.{frappe.generate_hash(length=8)}@example.test"
		frappe.set_user(self.owner)
		invitation_name = frappe.get_doc("Team", self.team.name).invite_member(email, "Viewer")

		frappe.set_user("Administrator")
		create_user(email)

		self.assertEqual(frappe.db.get_value("Team Invitation", invitation_name, "status"), "Pending")
		self.assertEqual(get_user_team_names(email), [])

	def test_bulk_invite_sends_each_row_and_returns_the_refused_ones(self):
		frappe.set_user(self.owner)
		frappe.clear_messages()
		results = invite_team_member(
			self.team.name,
			invitations=[
				{"email": "bulk.one@example.test", "role": "Developer"},
				{"email": "not-an-email", "role": "Developer"},
				{"email": self.admin, "role": "Viewer"},
				{"role": "Developer"},
				{"email": "bulk.norole@example.test"},
			],
		)

		self.assertTrue(results[0]["invitation"])
		self.assertIsNone(results[0]["error"])
		self.assertTrue(results[1]["error"])
		self.assertTrue(results[2]["error"])
		self.assertEqual(results[3]["error"], "Email and role are required.")
		self.assertEqual(results[4]["error"], "Email and role are required.")
		self.assertEqual(frappe.db.count("Team Invitation", {"team": self.team.name, "status": "Pending"}), 1)
		self.assertEqual(frappe.get_message_log(), [])

	def test_bulk_invite_is_limited_to_ten_people(self):
		frappe.set_user(self.owner)
		rows = [{"email": f"bulk.{n}@example.test", "role": "Developer"} for n in range(11)]

		with self.assertRaises(frappe.ValidationError):
			invite_team_member(self.team.name, invitations=rows)
		with self.assertRaises(frappe.ValidationError):
			invite_team_member(self.team.name, invitations=[])
		self.assertFalse(frappe.db.exists("Team Invitation", {"email": "bulk.0@example.test"}))

	def test_invite_without_an_email_or_rows_is_refused(self):
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.ValidationError):
			invite_team_member(self.team.name, role="Developer")

	def test_bulk_invite_needs_manage_members(self):
		frappe.set_user(self.viewer)

		with self.assertRaises(frappe.PermissionError):
			invite_team_member(
				self.team.name, invitations=[{"email": "bulk.viewer@example.test", "role": "Viewer"}]
			)

	def test_resend_issues_a_new_token(self):
		frappe.set_user(self.owner)
		name = invite_team_member(self.team.name, self.invitee, "Developer")
		# An invitation from before tokens existed has none.
		frappe.db.set_value("Team Invitation", name, "token", None)

		resend_invitation(name)

		self.assertTrue(frappe.db.get_value("Team Invitation", name, "token"))

	def test_team_logo_needs_team_edit_and_a_file_uploaded_to_the_team(self):
		frappe.set_user(self.owner)
		file_url = upload_test_image("Team", self.team.name, "team_logo")
		self.assertEqual(set_team_logo(self.team.name, file_url)["team_logo"], file_url)
		self.assertIsNone(set_team_logo(self.team.name, None)["team_logo"])

		with self.assertRaises(frappe.ValidationError):
			set_team_logo(self.team.name, "/files/somewhere-else.png")

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_team_logo(self.team.name, file_url)

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

	def test_a_role_cannot_carry_a_capability_its_creator_lacks(self):
		frappe.set_user(self.admin)
		with self.assertRaisesRegex(frappe.PermissionError, "team:delete"):
			create_custom_role(self.team.name, "Deleter", ["team:delete"])

		role = create_custom_role(self.team.name, "Viewer Twice", ["server:view", "server:view"])["role"]
		self.assertEqual(
			frappe.get_all("Role Capability", {"parent": role}, pluck="capability"), ["server:view"]
		)

		frappe.set_user(self.owner)
		create_custom_role(self.team.name, "Owner Deleter", ["team:delete"])

	def test_a_new_team_cannot_enrol_other_people(self):
		invitee_teams = get_user_team_names(self.invitee)
		frappe.set_user(self.viewer)
		team = {"doctype": "Team", "team_name": "Not Theirs"}

		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{**team, "members": [{"user": self.invitee, "role": "Admin", "status": "Active"}]}
			).insert()
		self.assertEqual(get_user_team_names(self.invitee), invitee_teams)

		created = frappe.get_doc(team).insert()
		self.assertEqual([(row.user, row.role) for row in created.members], [(self.viewer, "Owner")])

	def test_member_can_hold_multiple_roles_with_unioned_capabilities(self):
		# A team-wide role and a role scoped to one server combine: the scoped role adds
		# its server capabilities on that server only, and never a team-wide one.
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		view_only = create_custom_role(self.team.name, "View Only", ["server:view"])["role"]

		team.set_member_roles(
			self.viewer,
			[
				{"role": view_only, "resource_type": "*"},
				{"role": "Developer", "resource_type": "Server", "resource_name": self.server},
			],
		)

		self.assertTrue(can(self.viewer, self.team.name, "server:view"))
		self.assertTrue(can(self.viewer, self.team.name, "server:power", server=self.server))
		self.assertFalse(can(self.viewer, self.team.name, "server:power"))
		self.assertFalse(can(self.viewer, self.team.name, "server:create"))

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

	def test_my_teams_carries_role_member_count_and_created(self):
		frappe.set_user(self.admin)
		rows = [row for row in my_teams() if row["name"] == self.team.name]

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["role"], "Admin")
		self.assertEqual(rows[0]["members"], 3)
		self.assertTrue(rows[0]["created"])

	def test_leave_team_rejects_a_non_member_before_reading_the_team(self):
		outsider = create_user("team.outsider@example.test")
		frappe.set_user(outsider)

		with self.assertRaises(frappe.PermissionError):
			leave_team(self.team.name)

	def test_leaving_cannot_carry_other_member_changes(self):
		frappe.set_user(self.viewer)
		team = frappe.get_doc("Team", self.team.name)
		for row in team._get_member_rows(self.viewer) + team._get_member_rows(self.admin):
			team.remove(row)

		with self.assertRaises(frappe.PermissionError):
			team.save(ignore_permissions=True)

	def test_member_leaves_but_owner_cannot(self):
		frappe.set_user(self.viewer)
		leave_team(self.team.name)

		team = frappe.get_doc("Team", self.team.name)
		self.assertFalse(team._get_member_rows(self.viewer))
		self.assertFalse(can(self.viewer, team.name, "server:view"))

		with self.assertRaises(frappe.PermissionError):
			leave_team(self.team.name)

		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			leave_team(self.team.name)

	# --- API endpoints (central.api.teams / central.api.identity) ----------------

	def test_create_team_makes_caller_the_owner(self):
		frappe.set_user(self.owner)
		result = create_team("Fresh Team")

		team = frappe.get_doc("Team", result["name"])
		self.assertEqual(team.owner_user, self.owner)
		self.assertEqual(team._get_member(self.owner).role, "Owner")
		self.assertTrue(can(self.owner, team.name, "team:delete"))

	def test_team_invitation_list_is_manager_only(self):
		frappe.set_user(self.owner)
		invitation = invite_team_member(self.team.name, self.invitee, "Developer")

		rows = frappe.get_list(
			"Team Invitation",
			filters={"team": self.team.name},
			fields=["name", "email", "status"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["name"], invitation)
		self.assertEqual(rows[0]["email"], self.invitee)
		self.assertEqual(rows[0]["status"], "Pending")

		frappe.set_user(self.viewer)
		self.assertEqual(
			frappe.get_list("Team Invitation", filters={"team": self.team.name}, pluck="name"),
			[],
		)
		self.assertFalse(frappe.has_permission("Team Invitation", "read", invitation))

	def test_invite_can_scope_role_to_a_resource(self):
		frappe.set_user(self.owner)
		name = invite_team_member(
			self.team.name,
			self.invitee,
			"Developer",
			resource_type="Server",
			resource_name=self.server,
		)

		invitation = frappe.get_doc("Team Invitation", name)
		self.assertEqual(invitation.resource_type, "Server")
		self.assertEqual(invitation.resource_name, self.server)

		frappe.set_user(self.invitee)
		invitation.accept()

		team = frappe.get_doc("Team", self.team.name)
		grant = team._get_member(self.invitee)
		self.assertEqual(grant.role, "Developer")
		self.assertEqual(grant.resource_type, "Server")
		self.assertEqual(grant.resource_name, self.server)

	@IntegrationTestCase.change_settings("Central Settings", invitation_expiry_days=10)
	def test_resend_invitation_extends_expiry_and_re_emails(self):
		frappe.set_user(self.owner)
		name = invite_team_member(self.team.name, self.invitee, "Developer")
		frappe.db.set_value("Team Invitation", name, "expires_on", add_days(today(), 1))

		with patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail") as sendmail:
			result = resend_invitation(name)

		sendmail.assert_called_once()
		self.assertEqual(str(result["expires_on"]), add_days(today(), 10))

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

	def test_two_custom_roles_get_distinct_names(self):
		# Regression: Team Role.autoname was `format:TEAM-ROLE-.#####`, which the
		# format: handler left as the literal string, so the FIRST custom role on a
		# site inserted and the SECOND raised DuplicateEntryError. Create two in one
		# test (each other test creates at most one and rolls back, hiding the bug).
		frappe.set_user(self.owner)
		first = create_custom_role(self.team.name, "Role One", ["server:view"])["role"]
		second = create_custom_role(self.team.name, "Role Two", ["server:snapshot"])["role"]

		self.assertNotEqual(first, second)
		self.assertTrue(first.startswith("TEAM-ROLE-"))
		self.assertTrue(second.startswith("TEAM-ROLE-"))
		# The malformed literal must never be a stored name.
		self.assertNotEqual(first, "TEAM-ROLE-.#####")
		self.assertNotEqual(second, "TEAM-ROLE-.#####")

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
		# The controller owns cleanup, so Desk and API deletion behave the same.
		frappe.set_user(self.owner)
		team = create_team("Team With Invite")["name"]
		invite = invite_team_member(team, "blocks.delete@example.test", "Viewer")

		frappe.delete_doc("Team", team)
		self.assertFalse(frappe.db.exists("Team", team))
		self.assertFalse(frappe.db.exists("Team Invitation", invite))


class TestTeamsSurfaceStaysSingleDoor(IntegrationTestCase):
	"""central.api.teams is the sole HTTP door for team/invitation mutations; the
	doc methods it delegates to stay internal. Re-whitelisting one would recreate a
	double surface (the bug this guards)."""

	def test_delegated_doc_methods_are_not_whitelisted(self):
		from central.identity.doctype.team.team import Team
		from central.identity.doctype.team_invitation.team_invitation import TeamInvitation

		for method in (Team.invite_member, TeamInvitation.accept, TeamInvitation.revoke):
			with self.subTest(method=method.__qualname__), self.assertRaises(frappe.PermissionError):
				frappe.is_whitelisted(method)
