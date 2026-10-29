import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime

from central.api.activity import team_activity
from central.permissions import activity_event_query_conditions, has_activity_event_permission
from central.tests.activity_test_base import SSH_KEY, SSH_KEY_2, ActivityTestBase
from central.tests.test_iam import ensure_user


class TestTeamActivity(ActivityTestBase):
	def test_team_events_follow_their_own_capability(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		team.team_name = f"{team.team_name} renamed"
		team.save()

		updated = self._latest_event("team.updated", team=self.team)
		self.assertEqual(updated.required_capability, "team:edit")
		self.assertTrue(has_activity_event_permission(updated, user=self.owner, ptype="read"))
		self.assertFalse(has_activity_event_permission(updated, user=self.viewer, ptype="read"))

		frappe.set_user("Administrator")
		new_member = ensure_user(f"activity.member.{frappe.generate_hash(length=6)}@example.test")
		self._add_member(new_member, "Viewer")
		added = self._latest_event("member.added", team=self.team)
		self.assertEqual(added.required_capability, "team:manage_members")
		self.assertTrue(has_activity_event_permission(added, user=self.owner, ptype="read"))
		self.assertFalse(has_activity_event_permission(added, user=self.viewer, ptype="read"))

		self.assertEqual(self._team_events(self.viewer, category="team"), [])
		self.assertEqual(self._team_events(self.viewer, category="member"), [])
		self.assertEqual(
			{event["event"] for event in self._team_events(self.owner, category="team")},
			{"team.created", "team.updated"},
		)
		self.assertIn(
			"member.added", {event["event"] for event in self._team_events(self.owner, category="member")}
		)

		conditions = activity_event_query_conditions(self.viewer)
		self.assertNotIn("team:edit", conditions)
		self.assertNotIn("team:manage_members", conditions)

	def test_team_edit_role_sees_team_events_without_server_view(self):
		editor = ensure_user(f"activity.editor.{frappe.generate_hash(length=6)}@example.test")
		frappe.set_user(self.owner)
		role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"team": self.team,
				"role_name": "Event Editor",
				"capabilities": [{"capability": "team:edit"}],
			}
		).insert(ignore_permissions=True)
		self._add_member(editor, role.name)

		conditions = activity_event_query_conditions(editor)
		self.assertIn("team:edit", conditions)
		self.assertNotIn("server:view", conditions)

		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		team.team_name = f"{team.team_name} edited"
		team.save()
		updated = self._latest_event("team.updated", team=self.team)

		self.assertTrue(has_activity_event_permission(updated, user=editor, ptype="read"))
		self.assertIn(
			"team.updated", {event["event"] for event in self._team_events(editor, category="team")}
		)
		self.assertEqual(self._team_events(editor, category="member"), [])

	def test_team_read_api_needs_membership(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			team_activity(team=self.team)

	def test_team_invitation_and_role_events(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		team.invite_member(f"invite.{frappe.generate_hash(length=6)}@example.test", "Viewer")
		invited = self._latest_event("invitation.sent", team=self.team)
		self.assertEqual(invited.required_capability, "team:manage_members")

		role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"team": self.team,
				"role_name": f"Event role {frappe.generate_hash(length=6)}",
				"capabilities": [{"capability": "team:edit"}],
			}
		).insert(ignore_permissions=True)
		created = self._latest_event("role.created", team=self.team)
		self.assertEqual(created.resource_name, role.name)

		role.delete(ignore_permissions=True)
		deleted = self._latest_event("role.deleted", team=self.team)
		self.assertEqual(deleted.resource_name, role.name)
		self.assertTrue(frappe.db.exists("Activity Event", created.name))

	def test_invitation_actions_are_recorded(self):
		frappe.set_user("Administrator")
		accept_email = ensure_user(f"activity.accept.{frappe.generate_hash(length=6)}@example.test")
		decline_email = ensure_user(f"activity.decline.{frappe.generate_hash(length=6)}@example.test")

		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		accepted_name = team.invite_member(accept_email, "Viewer")
		sent = self._latest_event("invitation.sent", team=self.team)
		self.assertEqual(
			{detail["label"]: detail["to"] for detail in json.loads(sent.details)},
			{"Email": accept_email, "Role": "Viewer"},
		)

		frappe.set_user(accept_email)
		frappe.get_doc("Team Invitation", accepted_name).accept()
		accepted = self._latest_event("invitation.accepted", team=self.team)
		self.assertEqual(accepted.actor, accept_email)
		self.assertTrue(
			frappe.db.exists(
				"Activity Event", {"event": "member.added", "team": self.team, "actor": accept_email}
			)
		)

		frappe.set_user(self.owner)
		declined_name = frappe.get_doc("Team", self.team).invite_member(decline_email, "Viewer")
		frappe.set_user(decline_email)
		frappe.get_doc("Team Invitation", declined_name).decline()
		self.assertEqual(self._latest_event("invitation.declined", team=self.team).actor, decline_email)

		frappe.set_user(self.owner)
		revoked_name = frappe.get_doc("Team", self.team).invite_member(
			f"activity.revoke.{frappe.generate_hash(length=6)}@example.test", "Viewer"
		)
		frappe.get_doc("Team Invitation", revoked_name).revoke()
		self.assertEqual(self._latest_event("invitation.revoked", team=self.team).actor, self.owner)

		resent_name = frappe.get_doc("Team", self.team).invite_member(
			f"activity.resend.{frappe.generate_hash(length=6)}@example.test", "Viewer"
		)
		frappe.db.set_value(
			"Team Invitation", resent_name, "modified", add_days(now_datetime(), -1), update_modified=False
		)
		frappe.get_doc("Team Invitation", resent_name).resend()
		self.assertEqual(self._latest_event("invitation.resent", team=self.team).status, "Pending")

		frappe.set_user("Administrator")
		expired_name = frappe.get_doc("Team", self.team).invite_member(
			f"activity.expire.{frappe.generate_hash(length=6)}@example.test", "Viewer"
		)
		frappe.db.set_value(
			"Team Invitation", expired_name, "expires_on", add_days(now_datetime(), -1), update_modified=False
		)
		from central.identity.doctype.team_invitation.team_invitation import expire_pending_invitations

		expire_pending_invitations()
		self.assertEqual(self._latest_event("invitation.expired", team=self.team).status, "Expired")

	def test_ssh_key_events_need_key_management(self):
		frappe.set_user(self.owner)
		key = frappe.get_doc(
			{
				"doctype": "Team SSH Key",
				"team": self.team,
				"title": "Laptop",
				"public_key": SSH_KEY,
			}
		).insert()
		added = self._latest_event("ssh_key.added", team=self.team)
		self.assertEqual(added.required_capability, "server:ssh-key")
		self.assertTrue(has_activity_event_permission(added, user=self.owner, ptype="read"))
		self.assertFalse(has_activity_event_permission(added, user=self.viewer, ptype="read"))

		key.title = "Work laptop"
		key.save()
		self.assertEqual(self._latest_event("ssh_key.renamed", team=self.team).resource_name, key.name)

		key.reload()
		key.public_key = SSH_KEY_2
		key.save()
		self.assertEqual(self._latest_event("ssh_key.rotated", team=self.team).resource_name, key.name)

		key.delete()
		self.assertEqual(self._latest_event("ssh_key.deleted", team=self.team).resource_name, key.name)

		self.assertEqual(self._team_events(self.viewer, category="access"), [])
		self.assertEqual(
			{"ssh_key.added", "ssh_key.renamed", "ssh_key.rotated", "ssh_key.deleted"},
			{event["event"] for event in self._team_events(self.owner, category="access")},
		)

	def test_site_and_domain_events(self):
		site = frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"activity-{frappe.generate_hash(length=8)}.example.test",
				"team": self.team,
				"server": self.server,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(self._latest_event("site.created", team=self.team).resource_name, site.name)
		self.assertEqual(
			{event["event"] for event in self._events(category="site")},
			{"site.created"},
		)

		frappe.set_user(self.owner)
		site.mark_claimed()
		self.assertEqual(self._latest_event("site.claimed", team=self.team).resource_name, site.name)

		domain = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": f"activity-{frappe.generate_hash(length=8)}.example.com",
				"team": self.team,
				"server": self.server,
				"region": "activity-test",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(self._latest_event("domain.added", team=self.team).resource_name, domain.name)

		with patch("central.infrastructure.doctype.site_domain.site_domain.Region.get_proxy_client"):
			domain.delete(ignore_permissions=True)
		self.assertEqual(self._latest_event("domain.removed", team=self.team).resource_name, domain.name)

		site.delete(ignore_permissions=True)
		self.assertEqual(self._latest_event("site.deleted", team=self.team).resource_name, site.name)

	def test_team_archive_and_impersonation(self):
		suffix = frappe.generate_hash(length=6)
		team_name = self._team(f"Archive {suffix}", {self.owner: "Owner"})
		frappe.set_user(self.owner)
		frappe.get_doc("Team", team_name).archive()
		self.assertTrue(
			frappe.db.exists(
				"Activity Event", {"event": "team.archived", "team": team_name, "status": "Archived"}
			)
		)

		frappe.set_user("Administrator")
		frappe.get_doc("Team", self.team).get_impersonation_url("Checking the account")
		self.assertTrue(frappe.db.exists("Activity Event", {"event": "team.impersonated", "team": self.team}))

	def test_team_lifecycle_and_ownership_events(self):
		suffix = frappe.generate_hash(length=6)
		team_name = self._team(f"Lifecycle {suffix}", {self.owner: "Owner"})
		frappe.set_user(self.owner)
		frappe.get_doc("Team", team_name).archive()
		self.assertTrue(frappe.db.exists("Activity Event", {"event": "team.archived", "team": team_name}))

		frappe.set_user("Administrator")
		frappe.get_doc("Team", team_name).restore()
		self.assertTrue(frappe.db.exists("Activity Event", {"event": "team.restored", "team": team_name}))

		frappe.get_doc("Team", team_name).suspend("Abuse check")
		self.assertTrue(frappe.db.exists("Activity Event", {"event": "team.suspended", "team": team_name}))

		frappe.get_doc("Team", team_name).unsuspend()
		self.assertTrue(frappe.db.exists("Activity Event", {"event": "team.unsuspended", "team": team_name}))

		frappe.set_user(self.owner)
		frappe.get_doc("Team", self.team).transfer_ownership(self.viewer)
		event = self._latest_event("team.ownership_transferred", team=self.team)
		self.assertEqual(event.required_capability, "team:manage_members")
		self.assertEqual(event.actor, self.owner)
		self.assertEqual(
			{detail["label"]: (detail["from"], detail["to"]) for detail in json.loads(event.details)},
			{"Owner": (self.owner, self.viewer)},
		)
		self.assertFalse(
			frappe.db.exists("Activity Event", {"event": "member.roles_changed", "team": self.team})
		)
