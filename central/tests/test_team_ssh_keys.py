from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from central.api.ssh_keys import rotate_team_ssh_key
from central.infrastructure.doctype.team_ssh_key.team_ssh_key import TeamSSHKey, fingerprint
from central.integrations.ssh_keys import _replace_server_keys
from central.permissions import team_ssh_key_has_permission, team_ssh_key_query_conditions
from central.resource_actions import resolve_team_ssh_keys


class TestTeamSSHKeys(TestCase):
	@staticmethod
	def throw(message, exception=frappe.ValidationError):
		raise exception(message)

	@patch("central.infrastructure.doctype.team_ssh_key.team_ssh_key._", side_effect=lambda value: value)
	@patch("central.infrastructure.doctype.team_ssh_key.team_ssh_key.frappe.throw", side_effect=throw)
	def test_fingerprint_rejects_a_private_key(self, _throw, _translate) -> None:
		with self.assertRaises(frappe.ValidationError):
			fingerprint("-----BEGIN OPENSSH PRIVATE KEY-----")

	@patch("central.permissions.user_has_operator_bypass", return_value=False)
	@patch("central.permissions.can_on_any_server")
	@patch("central.permissions.can")
	def test_read_and_write_permissions_are_separate(self, can, on_any_server, _operator) -> None:
		# Reading needs server:view on any server of the team; writing needs server:ssh-key team-wide.
		on_any_server.side_effect = (
			lambda user, team, capability: team == "team-a" and capability == "server:view"
		)
		can.return_value = False
		doc = SimpleNamespace(team="team-a")
		self.assertTrue(team_ssh_key_has_permission(doc, "viewer", "read"))
		self.assertFalse(team_ssh_key_has_permission(doc, "viewer", "write"))
		self.assertFalse(team_ssh_key_has_permission(SimpleNamespace(team="team-b"), "viewer", "read"))

	@patch("central.permissions.user_has_operator_bypass", return_value=False)
	@patch("central.permissions.get_user_team_names_with_capability", return_value=[])
	def test_query_denies_users_without_server_view(self, _teams, _operator) -> None:
		self.assertEqual(team_ssh_key_query_conditions("outsider"), "1 = 0")

	@patch("central.resource_actions.frappe.get_list")
	@patch("central.resource_actions._", side_effect=lambda value: value)
	@patch("central.resource_actions.frappe.throw", side_effect=throw)
	def test_selected_keys_must_all_belong_to_the_team(self, _throw, _translate, get_list) -> None:
		get_list.return_value = [SimpleNamespace(name="own", public_key="ssh-ed25519 AAAA")]
		with self.assertRaises(frappe.PermissionError):
			resolve_team_ssh_keys("team-a", ["own", "other-team"])

	@patch("central.api.ssh_keys.require_access")
	@patch("central.api.ssh_keys.frappe.get_doc", return_value=SimpleNamespace(team="team-b"))
	@patch("central.api.ssh_keys.frappe.throw", side_effect=throw)
	@patch("central.api.ssh_keys._", side_effect=lambda value: value)
	def test_rotation_rejects_a_key_from_another_team(self, _translate, _throw, _key, _access) -> None:
		with self.assertRaises(frappe.PermissionError):
			rotate_team_ssh_key("team-a", "key-b", "ssh-ed25519 AAAA")

	def _delete_key(self, rows: list) -> None:
		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *_: False),
			get_all=lambda *_, **__: rows,
			throw=self.throw,
		)
		with patch("central.infrastructure.doctype.team_ssh_key.team_ssh_key.frappe", fake_frappe):
			with patch(
				"central.infrastructure.doctype.team_ssh_key.team_ssh_key._", side_effect=lambda value: value
			):
				TeamSSHKey.on_trash(SimpleNamespace(name="key-a", team="team-a"))

	def test_pending_creation_prevents_key_deletion(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self._delete_key(
				[
					SimpleNamespace(
						status="Queued", remote_vm_id=None, request_payload='{"ssh_key_ids":["key-a"]}'
					)
				]
			)

	def test_retryable_failed_creation_prevents_key_deletion(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self._delete_key(
				[
					SimpleNamespace(
						status="Failed", remote_vm_id=None, request_payload='{"ssh_key_ids":["key-a"]}'
					)
				]
			)

	def test_failed_creation_with_a_vm_does_not_block_key_deletion(self) -> None:
		self._delete_key(
			[
				SimpleNamespace(
					status="Failed", remote_vm_id="vm-1", request_payload='{"ssh_key_ids":["key-a"]}'
				)
			]
		)

	@patch("central.integrations.ssh_keys.AtlasClient")
	@patch("central.integrations.ssh_keys.frappe.get_doc", return_value=SimpleNamespace(name="region-a"))
	@patch("central.integrations.ssh_keys.frappe.get_cached_value", return_value=12)
	@patch("central.integrations.ssh_keys.frappe.get_all")
	def test_rotation_replaces_all_selected_keys(self, get_all, _tenant, _region, atlas_client) -> None:
		get_all.side_effect = [
			[SimpleNamespace(team_ssh_key="key-a"), SimpleNamespace(team_ssh_key="key-b")],
			[
				SimpleNamespace(name="key-a", public_key="new-a"),
				SimpleNamespace(name="key-b", public_key="existing-b"),
			],
		]
		server = SimpleNamespace(name="server-a", team="team-a", region="region-a", atlas_vm_id="vm-a")
		_replace_server_keys(server)
		atlas_client.return_value.replace_vm_ssh_keys.assert_called_once_with("vm-a", ["new-a", "existing-b"])
