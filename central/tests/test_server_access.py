from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.activity import server_activity
from central.api.servers import get_rescue_state, set_rescue_mode, set_termination_protection
from central.api.ssh_keys import set_server_ssh_keys
from central.errors import AtlasConnectionError, AtlasRejected
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.resource_actions import submit_command
from central.tests.test_iam import ensure_user
from central.tests.test_server_overview import make_public_key
from central.tests.utils import ensure_atlas_instance


class TestServerAccess(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.db.commit"))
		self.enterContext(patch.object(VirtualMachine, "sync_subscription_on_status_change"))

		self.developer = ensure_user("access.developer@example.test")
		self.viewer = ensure_user("access.viewer@example.test")
		self.team = self._team("Access A", {self.developer: "Developer", self.viewer: "Viewer"})
		self.other_team = self._team("Access B", {})
		region = ensure_atlas_instance("test-access")
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "access-" + frappe.generate_hash(length=8),
				"team": self.team,
				"atlas_vm_id": "vm-access",
				"region": region,
				"status": "Running",
			}
		).insert()

		self.first_key = self._key(self.team, "Laptop")
		self.second_key = self._key(self.team, "CI")
		self.foreign_key = self._key(self.other_team, "Foreign")
		self.ssh_client = self.enterContext(patch("central.integrations.ssh_keys.get_client")).return_value
		self.server_client = self.enterContext(patch("central.integrations.servers.get_client")).return_value

	def _team(self, name: str, roles: dict[str, str]) -> str:
		members = [{"user": user, "role": role, "status": "Active"} for user, role in roles.items()]
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": name, "owner_user": "Administrator", "members": members}
		)

		return team.insert().name

	def _key(self, team: str, title: str):
		return frappe.get_doc(
			{"doctype": "Team SSH Key", "team": team, "title": title, "public_key": make_public_key()}
		).insert()

	def _saved_keys(self) -> list[str]:
		return [row.team_ssh_key for row in frappe.get_doc("Virtual Machine", self.server.name).ssh_keys]

	def test_keys_are_sent_to_the_region_then_saved_in_order(self):
		frappe.set_user(self.developer)
		set_server_ssh_keys(self.team, self.server.name, [self.second_key.name, self.first_key.name])

		self.ssh_client.replace_vm_ssh_keys.assert_called_once_with(
			"vm-access", [self.second_key.public_key, self.first_key.public_key]
		)
		self.assertEqual(self._saved_keys(), [self.second_key.name, self.first_key.name])

	def test_a_viewer_cannot_change_keys(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_server_ssh_keys(self.team, self.server.name, [self.first_key.name])

		self.ssh_client.replace_vm_ssh_keys.assert_not_called()

	def test_a_key_of_another_team_is_refused(self):
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.PermissionError):
			set_server_ssh_keys(self.team, self.server.name, [self.foreign_key.name])

		self.ssh_client.replace_vm_ssh_keys.assert_not_called()

	def test_a_region_failure_keeps_the_saved_keys(self):
		self.ssh_client.replace_vm_ssh_keys.side_effect = AtlasRejected("refused")
		frappe.set_user(self.developer)
		with self.assertRaises(AtlasConnectionError):
			set_server_ssh_keys(self.team, self.server.name, [self.first_key.name])

		self.assertEqual(self._saved_keys(), [])

	def test_a_terminated_server_keeps_its_keys(self):
		self.server.db_set("status", "Terminated")
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.ValidationError):
			set_server_ssh_keys(self.team, self.server.name, [self.first_key.name])

		self.ssh_client.replace_vm_ssh_keys.assert_not_called()

	def test_protection_records_the_state_the_region_reports(self):
		self.server_client.set_termination_protection.return_value = {"is_termination_protected": True}
		frappe.set_user(self.developer)

		set_termination_protection(self.team, self.server.name, enabled=1)

		self.server_client.set_termination_protection.assert_called_once_with("vm-access", True)
		self.assertTrue(frappe.db.get_value("Virtual Machine", self.server.name, "is_termination_protected"))

	def test_a_protection_change_shows_in_the_server_activity(self):
		self.server_client.set_termination_protection.return_value = {"is_termination_protected": True}
		frappe.set_user(self.developer)

		set_termination_protection(self.team, self.server.name, enabled=1)

		events = server_activity(team=self.team, resource_id=self.server.resource_id)["events"]
		self.assertEqual(events[0]["event"], "server.updated")
		self.assertEqual(
			events[0]["details"], [{"label": "Termination protection", "from": "off", "to": "on"}]
		)

	def test_protection_refuses_an_unexpected_region_reply(self):
		self.server_client.set_termination_protection.return_value = {}
		frappe.set_user(self.developer)
		with self.assertRaises(AtlasConnectionError):
			set_termination_protection(self.team, self.server.name, enabled=1)

		self.assertFalse(frappe.db.get_value("Virtual Machine", self.server.name, "is_termination_protected"))

	def test_a_viewer_cannot_change_protection(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_termination_protection(self.team, self.server.name, enabled=1)

		self.server_client.set_termination_protection.assert_not_called()

	@patch("frappe.enqueue")
	def test_a_protected_server_is_not_terminated(self, enqueue):
		self.server.db_set("is_termination_protected", 1)
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.ValidationError):
			submit_command("terminate", self.team, self.server.name)

		enqueue.assert_not_called()
		self.assertFalse(frappe.db.exists("Resource Action", {"server": self.server.name}))

	def test_rescue_selection_does_not_restart_or_write_observed_state(self):
		frappe.set_user(self.developer)
		set_rescue_mode(enabled=True, team=self.team, resource_id=self.server.name)
		self.server_client.set_rescue_mode.assert_called_once_with("vm-access", True)
		self.server_client.vm_action.assert_not_called()
		self.server_client.get_vm.assert_not_called()
		self.assertEqual(self.server.reload().status, "Running")

	def test_rescue_read_preserves_unknown_mode(self):
		self.server_client.tenant_id = 42
		self.server_client.get_vm.return_value = {
			"id": "vm-access",
			"tenant_id": 42,
			"is_rescue_mode_enabled": True,
			"is_in_rescue_mode": None,
		}
		frappe.set_user(self.viewer)
		self.assertEqual(
			get_rescue_state(team=self.team, resource_id=self.server.name),
			{
				"is_rescue_mode_enabled": True,
				"is_in_rescue_mode": None,
			},
		)

	def test_rescue_selection_requires_both_capabilities(self):
		for missing in ("server:power", "server:console"):
			with (
				self.subTest(missing=missing),
				patch(
					"central.infrastructure.doctype.virtual_machine.virtual_machine.can",
					side_effect=lambda user, team, capability, **kwargs: capability != missing,
				),
				self.assertRaises(frappe.PermissionError),
			):
				self.server.set_rescue_mode(True)
		self.server_client.set_rescue_mode.assert_not_called()

	def test_rescue_read_rejects_another_tenant_and_malformed_state(self):
		from central.integrations.servers import get_rescue_state as read

		self.server_client.tenant_id = 42
		for changes in ({"tenant_id": 43}, {"id": "another-vm"}, {"is_in_rescue_mode": "false"}):
			self.server_client.get_vm.return_value = {
				"id": "vm-access",
				"tenant_id": 42,
				"is_rescue_mode_enabled": False,
				"is_in_rescue_mode": False,
				**changes,
			}
			with self.subTest(changes=changes), self.assertRaises(AtlasConnectionError):
				read(self.server)

	def test_rescue_rejects_cross_team_and_viewer_mutations(self):
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.PermissionError):
			set_rescue_mode(enabled=True, team=self.other_team, resource_id=self.server.name)
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_rescue_mode(enabled=True, team=self.team, resource_id=self.server.name)
		self.server_client.set_rescue_mode.assert_not_called()

	def test_rescue_uncertain_reply_does_not_retry(self):
		from central.errors import AtlasRequestUncertain, ResourceActionError

		self.server_client.set_rescue_mode.side_effect = AtlasRequestUncertain("lost reply")
		with self.assertRaises(ResourceActionError) as caught:
			self.server.set_rescue_mode(True)
		self.assertEqual(caught.exception.envelope["code"], "OUTCOME_UNKNOWN")
		self.assertIn("Refresh rescue status", caught.exception.envelope["remediation"])
		self.server_client.set_rescue_mode.assert_called_once_with("vm-access", True)

	def test_rescue_selection_requires_an_explicit_boolean(self):
		for enabled in (None, "false", 2):
			with self.subTest(enabled=enabled), self.assertRaises(frappe.ValidationError):
				self.server.set_rescue_mode(enabled)
		self.server_client.set_rescue_mode.assert_not_called()

	def test_rescue_selection_rejects_terminated_servers(self):
		self.server.status = "Terminated"
		with self.assertRaises(frappe.ValidationError):
			self.server.set_rescue_mode(True)
		self.server_client.set_rescue_mode.assert_not_called()
