from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.identity import my_capabilities
from central.api.servers import registry, resize_server, server_overview
from central.api.sites import authorized_site
from central.api.snapshots import keep_snapshot, list_snapshots, take_snapshot
from central.api.sso import get_bench_link
from central.billing.api.dashboard.catalog import get_composed_config, get_eligible_plans
from central.iam import (
	ALL_SERVERS,
	can,
	can_on_any_server,
	clear_grants_cache,
	get_allowed_servers,
	get_server_capabilities,
)
from central.integrations.servers import process_command
from central.notification import create_notification, list_notifications
from central.notification.engine import dispatch
from central.resource_actions import submit_command
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_server

SERVER_CAPABILITIES = [
	"server:power",
	"server:resize",
	"server:snapshot",
	"server:terminate",
	"server:view",
]


class ResourceScopingTestCase(IntegrationTestCase):
	"""A team with two servers, a member scoped to one of them, and a second team."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("scope.owner@example.test")
		self.scoped = ensure_user("scope.developer@example.test")
		self.viewer = ensure_user("scope.viewer@example.test")
		self.suffix = suffix = frappe.generate_hash(length=6)
		self.team = self._team(f"Scope Team {suffix}")
		self.other_team = self._team(f"Scope Other Team {suffix}")
		self.mine = ensure_server(f"scope-mine-{suffix}", self.team)
		self.theirs = ensure_server(f"scope-theirs-{suffix}", self.team)
		self.elsewhere = ensure_server(f"scope-elsewhere-{suffix}", self.other_team)
		self._grant(self.scoped, "Developer", "Server", self.mine)
		self._grant(self.viewer, "Viewer", "*", None)

	def tearDown(self):
		frappe.set_user("Administrator")
		clear_grants_cache()

	def _team(self, name: str) -> str:
		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		team = {"doctype": "Team", "team_name": name, "owner_user": self.owner, "members": members}
		return frappe.get_doc(team).insert().name

	def _grant(self, user: str, role: str, resource_type: str, resource_name: str | None) -> None:
		team = frappe.get_doc("Team", self.team)
		team.append(
			"members",
			{
				"user": user,
				"role": role,
				"resource_type": resource_type,
				"resource_name": resource_name,
				"status": "Active",
			},
		)
		team.save()
		clear_grants_cache()

	def _insert(self, doc: dict) -> str:
		"""Write a record without its lifecycle hooks, which would call a region."""
		record = frappe.get_doc(doc)
		record.name = record.name or frappe.generate_hash(length=10)
		record.db_insert()
		return record.name


class TestScopedCapabilities(ResourceScopingTestCase):
	def test_a_scoped_grant_acts_on_its_server_only(self):
		self.assertTrue(can(self.scoped, self.team, "server:power", server=self.mine))
		self.assertFalse(can(self.scoped, self.team, "server:power", server=self.theirs))
		self.assertFalse(can(self.scoped, self.team, "server:power"))

	def test_a_scoped_grant_never_answers_a_team_wide_capability(self):
		for capability in ("server:create", "server:ssh-key", "cluster:view", "service:manage"):
			with self.subTest(capability=capability):
				self.assertFalse(can(self.scoped, self.team, capability))
				self.assertFalse(can(self.scoped, self.team, capability, server=self.mine))
				self.assertFalse(can_on_any_server(self.scoped, self.team, capability))

	def test_a_team_wide_grant_covers_every_server(self):
		self.assertTrue(can(self.viewer, self.team, "server:view"))
		self.assertTrue(can(self.viewer, self.team, "server:view", server=self.theirs))
		self.assertEqual(get_allowed_servers(self.viewer, "server:view")[self.team], ALL_SERVERS)

	def test_the_scope_lists_the_scoped_servers(self):
		allowed = get_allowed_servers(self.scoped, "server:view")
		self.assertEqual(allowed[self.team], frozenset({self.mine}))
		self.assertNotIn(self.other_team, allowed)
		self.assertTrue(can_on_any_server(self.scoped, self.team, "server:view"))

	def test_a_site_grant_applies_to_the_site_server(self):
		site = self._insert(
			{
				"doctype": "Site",
				"site_name": f"scope-{self.suffix}.example.test",
				"team": self.team,
				"server": self.theirs,
			}
		)
		self._grant(self.scoped, "Viewer", "Site", site)

		self.assertTrue(can(self.scoped, self.team, "server:view", server=self.theirs))
		self.assertFalse(can(self.scoped, self.team, "server:power", server=self.theirs))

	def test_a_grant_on_a_removed_server_grants_nothing(self):
		frappe.delete_doc("Virtual Machine", self.mine, force=True, ignore_permissions=True)
		clear_grants_cache()

		self.assertFalse(can(self.scoped, self.team, "server:power", server=self.mine))

	def test_console_capabilities_list_server_caps_but_no_team_caps(self):
		frappe.set_user(self.scoped)
		caps = my_capabilities(self.team)

		self.assertEqual(caps, SERVER_CAPABILITIES)
		self.assertEqual(get_server_capabilities(self.scoped, self.team, self.theirs), [])


class TestScopedGrantValidation(ResourceScopingTestCase):
	def test_a_grant_must_name_a_server_of_the_team(self):
		for name in (self.elsewhere, "no-such-server"):
			with self.subTest(name=name), self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
				self._grant(self.scoped, "Viewer", "Server", name)

	def test_the_owner_role_is_always_team_wide(self):
		team = frappe.get_doc("Team", self.team)
		owner_row = next(row for row in team.members if row.role == "Owner")
		owner_row.resource_type, owner_row.resource_name = "Server", self.mine

		with self.assertRaisesRegex(frappe.ValidationError, "all resources"):
			team.save()

	def test_an_invitation_must_name_a_server_of_the_team(self):
		invitation = {
			"doctype": "Team Invitation",
			"team": self.team,
			"email": "scope.invitee@example.test",
			"role": "Developer",
			"resource_type": "Server",
			"resource_name": self.elsewhere,
		}
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
			frappe.get_doc(invitation).insert()


class TestScopedRecords(ResourceScopingTestCase):
	def test_lists_show_only_the_scoped_server_and_its_records(self):
		for server in (self.mine, self.theirs):
			self._insert(
				{
					"doctype": "VM Snapshot",
					"title": server,
					"team": self.team,
					"server": server,
					"snapshot_type": "Manual",
				}
			)
		creation = self._insert(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "create",
				"team": self.team,
				"correlation_id": frappe.generate_hash(),
			}
		)

		frappe.set_user(self.scoped)
		self.assertEqual(
			frappe.get_list("Virtual Machine", filters={"team": self.team}, pluck="name"), [self.mine]
		)
		self.assertEqual(
			frappe.get_list("VM Snapshot", filters={"team": self.team}, pluck="server"), [self.mine]
		)
		self.assertNotIn(
			creation, frappe.get_list("Resource Action", filters={"team": self.team}, pluck="name")
		)

	def test_a_record_on_another_server_cannot_be_read(self):
		frappe.set_user(self.scoped)

		self.assertTrue(frappe.has_permission("Virtual Machine", "read", self.mine))
		self.assertFalse(frappe.has_permission("Virtual Machine", "read", self.theirs))
		self.assertFalse(frappe.has_permission("Virtual Machine", "write", self.mine))

	def test_a_team_wide_viewer_still_sees_every_server(self):
		frappe.set_user(self.viewer)

		names = set(frappe.get_list("Virtual Machine", filters={"team": self.team}, pluck="name"))
		self.assertEqual(names, {self.mine, self.theirs})


class TestScopedRoutes(ResourceScopingTestCase):
	def test_registry_lists_only_the_scoped_server_with_its_capabilities(self):
		frappe.set_user(self.scoped)
		servers = registry(self.team)["servers"]

		self.assertEqual([server["name"] for server in servers], [self.mine])
		self.assertEqual(servers[0]["capabilities"], SERVER_CAPABILITIES)

	def test_one_server_routes_refuse_another_server(self):
		frappe.set_user(self.scoped)
		for call in (
			lambda: server_overview(self.team, self.theirs),
			lambda: resize_server(self.team, self.theirs, plan="any"),
			lambda: take_snapshot(self.team, self.theirs),
			lambda: submit_command("stop", self.team, self.theirs),
			lambda: get_bench_link(server=self.theirs),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_commands_on_the_scoped_server_pass_the_permission_check(self):
		frappe.set_user(self.scoped)

		# Each call reaches its own state check, which proves it passed authorization.
		with self.assertRaisesRegex(frappe.ValidationError, "verified regional identity"):
			submit_command("stop", self.team, self.mine)
		with self.assertRaisesRegex(frappe.ValidationError, "bench gateway"):
			get_bench_link(server=self.mine)

	def test_snapshot_routes_check_the_snapshot_server(self):
		mine = self._insert(
			{
				"doctype": "VM Snapshot",
				"title": "mine",
				"team": self.team,
				"server": self.mine,
				"snapshot_type": "Manual",
				"status": "Pending",
			}
		)
		theirs = self._insert(
			{
				"doctype": "VM Snapshot",
				"title": "theirs",
				"team": self.team,
				"server": self.theirs,
				"snapshot_type": "Manual",
				"status": "Available",
			}
		)

		frappe.set_user(self.scoped)
		with self.assertRaises(frappe.PermissionError):
			keep_snapshot(self.team, theirs)
		with self.assertRaisesRegex(frappe.ValidationError, "available snapshot"):
			keep_snapshot(self.team, mine)
		self.assertEqual([row["name"] for row in list_snapshots(self.team)["snapshots"]], [mine])

	def test_a_site_on_another_server_is_refused(self):
		site = self._insert(
			{
				"doctype": "Site",
				"site_name": f"scope-theirs-{self.suffix}.example.test",
				"team": self.team,
				"server": self.theirs,
			}
		)

		frappe.set_user(self.scoped)
		with self.assertRaises(frappe.PermissionError):
			authorized_site(site, "server:view")


class TestScopedNotifications(ResourceScopingTestCase):
	def _notify(self, server: str | None, required_cap: str = "server:view") -> str:
		reference = {"reference_doctype": "Virtual Machine", "reference_name": server} if server else {}
		return create_notification(
			self.team,
			f"About {server}",
			category="Server",
			required_cap=required_cap,
			publish=False,
			**reference,
		).name

	def _feed(self, user: str) -> set[str]:
		return {row["name"] for row in list_notifications(self.team, user=user, limit=100)["items"]}

	def test_the_feed_shows_a_scoped_member_only_its_server(self):
		mine, theirs, team_wide = self._notify(self.mine), self._notify(self.theirs), self._notify(None)
		billing = self._notify(None, required_cap="billing:view")

		self.assertEqual(frappe.db.get_value("Team Notification", mine, "server"), self.mine)
		feed = self._feed(self.scoped)
		self.assertIn(mine, feed)
		self.assertNotIn(theirs, feed)
		self.assertNotIn(team_wide, feed)
		self.assertNotIn(billing, feed)
		self.assertTrue({mine, theirs, team_wide} <= self._feed(self.viewer))

	def test_emails_go_to_a_scoped_member_only_for_its_server(self):
		frappe.db.delete("Notification Event Type", {"event_type": "scope_test_event"})
		frappe.get_doc(
			{
				"doctype": "Notification Event Type",
				"event_type": "scope_test_event",
				"category": "Server",
				"severity": "Info",
				"required_cap": "server:view",
				"in_app_title": "Scope test",
				"in_app_body": "{{ message }}",
				"direct_recipients": "None",
				"create_in_app": 0,
			}
		).insert(ignore_permissions=True)

		recipients = {}
		for server in (self.mine, self.theirs):
			with patch("central.notification.engine._send_member_email", return_value=True) as send:
				dispatch(
					self.team, "scope_test_event", reference_doctype="Virtual Machine", reference_name=server
				)
			recipients[server] = {call.args[0] for call in send.call_args_list}

		self.assertIn(self.scoped, recipients[self.mine])
		self.assertNotIn(self.scoped, recipients[self.theirs])
		self.assertIn(self.viewer, recipients[self.theirs])


class TestScopedDispatch(ResourceScopingTestCase):
	def _queue(self, server: str) -> str:
		vm_id = frappe.generate_hash(length=8)
		frappe.db.set_value("Virtual Machine", server, "atlas_vm_id", vm_id)
		return self._insert(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "stop",
				"team": self.team,
				"region": "scope-test",
				"server": server,
				"resource_id": server,
				"remote_vm_id": vm_id,
				"requested_by": self.scoped,
				"correlation_id": frappe.generate_hash(),
				"status": "Queued",
			}
		)

	def test_a_queued_command_outside_the_scope_is_refused_before_the_region(self):
		name = self._queue(self.theirs)

		with patch("central.integrations.servers._client") as client:
			process_command(frappe.get_doc("Resource Action", name))

		self.assertEqual(frappe.db.get_value("Resource Action", name, "status"), "Failed")
		client.assert_not_called()

	def test_a_queued_command_on_the_scoped_server_reaches_the_region(self):
		name = self._queue(self.mine)

		with patch("central.integrations.servers._client") as client:
			client.side_effect = RuntimeError("stop here")
			with self.assertRaisesRegex(RuntimeError, "stop here"):
				process_command(frappe.get_doc("Resource Action", name))

		client.assert_called_once()


class TestScopedResizePricing(ResourceScopingTestCase):
	"""Pricing a resize needs server:resize on that server; anyone else needs billing:view."""

	def _subscription(self, server: str) -> str:
		return self._insert({"doctype": "Subscription", "team": self.team, "server_id": server, "enabled": 1})

	def test_the_resize_config_follows_server_resize(self):
		frappe.set_user(self.scoped)
		self.assertIn("resizable", get_composed_config(self.mine, self.team))
		with self.assertRaises(frappe.PermissionError):
			get_composed_config(self.theirs, self.team)

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			get_composed_config(self.mine, self.team)

	def test_resize_plans_follow_server_resize(self):
		mine, theirs = self._subscription(self.mine), self._subscription(self.theirs)

		frappe.set_user(self.scoped)
		with patch("central.billing.catalog.server_plans.get_server_plans", return_value={}) as plans:
			get_eligible_plans(team=self.team, exclude_subscription=mine, for_resize=1)
			with self.assertRaises(frappe.PermissionError):
				get_eligible_plans(team=self.team, exclude_subscription=theirs, for_resize=1)
			with self.assertRaises(frappe.PermissionError):
				get_eligible_plans(team=self.team)

		self.assertEqual(plans.call_args.args, (self.team,))

	def test_a_team_wide_developer_without_billing_view_can_price_a_resize(self):
		developer = ensure_user("scope.teamdeveloper@example.test")
		self._grant(developer, "Developer", "*", None)
		subscription = self._subscription(self.theirs)

		frappe.set_user(developer)
		with patch("central.billing.catalog.server_plans.get_server_plans", return_value={}):
			get_eligible_plans(team=self.team, exclude_subscription=subscription, for_resize=1)
		get_composed_config(self.theirs, self.team)
