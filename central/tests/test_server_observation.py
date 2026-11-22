from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.errors import AtlasConnectionError, AtlasResourceGone
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.servers import observe_server


class TestServerObservation(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "ensure_subscription_enabled"))
		self.cancel_billing = self.enterContext(patch.object(VirtualMachine, "disable_active_subscription"))
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": "Mirror", "owner_user": "Administrator"}
		).insert()
		region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": "mirror-" + frappe.generate_hash(length=8),
				"base_url": "https://atlas.example.test",
				"proxy_domain": "par-2.example.test",
				"status": "Active",
			}
		).insert()
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "server-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"region": region.name,
				"atlas_vm_id": "vm-00001",
				"status": "Provisioning",
			}
		).insert()
		self.client = self.enterContext(patch("central.integrations.servers.AtlasClient")).return_value
		self.client.tenant_id = self.team.tenant_id
		self.client.get_vm.return_value = {
			"id": "vm-00001",
			"tenant_id": self.team.tenant_id,
			"current_state": "running",
			"error": None,
			"compute": {"cpu_millicores": 1000, "memory_mib": 512},
			"disk": {"size_mib": 20480},
			"network": {"mesh_ipv6": "fdaa:1::1", "public_ipv4": None},
		}

	def test_observation_closes_the_action_waiting_for_that_state(self):
		action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "stop",
				"team": self.team.name,
				"region": self.server.region,
				"server": self.server.name,
				"resource_id": self.server.name,
				"remote_vm_id": "vm-00001",
				"requested_by": "Administrator",
				"correlation_id": frappe.generate_hash(length=32),
				"status": "In Progress",
			}
		).insert(ignore_permissions=True)
		self.client.get_vm.return_value["current_state"] = "stopped"

		self.assertEqual(observe_server(self.server), "Stopped")
		self.assertEqual(frappe.db.get_value("Resource Action", action.name, "status"), "Succeeded")

	def test_observation_preserves_local_and_regional_identity(self):
		self.assertEqual(observe_server(self.server), "Running")
		self.server.reload()
		self.assertEqual(self.server.atlas_vm_id, "vm-00001")
		self.assertEqual(self.server.memory_megabytes, 512)
		self.assertTrue(self.server.name.startswith("server-"))
		self.client.get_vm.assert_called_once_with("vm-00001")

	def test_observation_records_public_addresses(self):
		self.client.get_vm.return_value["network"].update(
			{"public_ipv4": "203.0.113.10", "public_ipv6": "2001:db8:5::7/128"}
		)

		observe_server(self.server)
		self.server.reload()
		self.assertEqual(self.server.public_ipv4, "203.0.113.10")
		self.assertEqual(self.server.public_ipv6, "2001:db8:5::7")

	def test_only_a_changed_report_saves_the_server(self):
		"""An unchanged report only moves the observation clock, so it writes no Version and runs
		no hooks."""
		save = self.enterContext(
			patch.object(VirtualMachine, "save", autospec=True, side_effect=VirtualMachine.save)
		)

		observe_server(self.server)
		observe_server(self.server)

		self.assertEqual(save.call_count, 1)

	def test_gateway_waits_for_an_enrolled_pilot(self):
		self.assertEqual(observe_server(self.server), "Running")
		self.assertIsNone(self.server.reload().gateway_url)

		PilotCredential.mint(
			team=self.team.name, pilot_credential_id="pcred-" + self.server.name, server=self.server.name
		)
		observe_server(self.server)
		self.assertEqual(self.server.reload().gateway_url, "https://admin-vm-1z141z4.par-2.example.test")

	def test_read_failure_never_means_terminated(self):
		self.client.get_vm.side_effect = AtlasConnectionError("unreachable")
		with self.assertRaises(AtlasConnectionError):
			observe_server(self.server)
		self.server.reload()
		self.assertEqual(self.server.status, "Provisioning")

	def test_scoped_absence_terminates_and_runs_billing_hook(self):
		self.client.get_vm.side_effect = AtlasResourceGone("gone")
		self.assertEqual(observe_server(self.server), "Terminated")
		self.server.reload()
		self.assertEqual(self.server.status, "Terminated")
		self.cancel_billing.assert_called_once()

	def test_cross_tenant_response_is_rejected_without_changing_the_record(self):
		self.client.get_vm.return_value["tenant_id"] += 1
		with self.assertRaises(AtlasConnectionError):
			observe_server(self.server)
		self.server.reload()
		self.assertEqual(self.server.status, "Provisioning")

	def test_older_report_cannot_regress_state(self):
		now = frappe.utils.now_datetime()
		self.server.db_set({"status": "Running", "last_reported_at": now})

		applied = self.server.record_observed_state(
			{"status": "Stopped"}, now, reported_at=frappe.utils.add_to_date(now, seconds=-1)
		)
		self.assertFalse(applied)
		self.assertEqual(self.server.reload().status, "Running")

	def test_report_writes_only_the_fields_it_carries(self):
		self.server.db_set({"public_ipv4": "203.0.113.7"})

		self.assertTrue(self.server.record_observed_state({"status": "Stopped"}, frappe.utils.now_datetime()))
		self.server.reload()
		self.assertEqual(self.server.status, "Stopped")
		self.assertEqual(self.server.public_ipv4, "203.0.113.7")

	def test_report_never_touches_a_field_Central_owns(self):
		self.server.db_set({"title": "acme-1", "plan": None})

		self.server.record_observed_state(
			{"status": "Running", "title": "vm-00001", "team": "another-team"}, frappe.utils.now_datetime()
		)
		self.server.reload()
		self.assertEqual(self.server.title, "acme-1")
		self.assertEqual(self.server.team, self.team.name)

	def test_a_recorded_report_reaches_only_the_owning_team(self):
		"""The console learns about its own servers through its team's room, so one
		team's traffic never reaches another's browser."""
		with patch("frappe.publish_realtime") as published:
			self.server.record_observed_state({"status": "Stopped"}, frappe.utils.now_datetime())

		# Frappe's own save() also publishes doc_update and list_update for Desk.
		published.assert_any_call(
			"server_state_changed",
			{"resource_id": self.server.name},
			doctype="Team",
			docname=self.team.name,
			after_commit=True,
		)

	def test_a_new_server_reaches_the_owning_team_before_its_first_report(self):
		with patch("frappe.publish_realtime") as published:
			server = frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": "server-" + frappe.generate_hash(length=8),
					"team": self.team.name,
					"region": self.server.region,
					"status": "Provisioning",
				}
			).insert()

		published.assert_any_call(
			"server_state_changed",
			{"resource_id": server.name},
			doctype="Team",
			docname=self.team.name,
			after_commit=True,
		)

	def test_a_report_that_changes_nothing_wakes_no_console(self):
		now = frappe.utils.now_datetime()
		self.server.db_set({"last_reported_at": now})

		with patch("frappe.publish_realtime") as published:
			# A stale (older) report changes nothing.
			self.server.record_observed_state(
				{"status": "Stopped"}, now, reported_at=frappe.utils.add_to_date(now, seconds=-1)
			)

		self.assertNotIn(
			"server_state_changed", [call.args[0] for call in published.call_args_list if call.args]
		)

	def test_a_newer_same_state_report_updates_only_the_watermark(self):
		now = frappe.utils.now_datetime()
		self.server.db_set({"status": "Stopped", "last_reported_at": now})
		modified = self.server.modified
		later = frappe.utils.add_to_date(now, seconds=1)

		with patch("frappe.publish_realtime") as published:
			self.assertTrue(
				self.server.record_observed_state({"status": "Stopped"}, later, reported_at=later)
			)

		self.assertEqual(frappe.utils.get_datetime(self.server.reload().last_reported_at), later)
		self.assertEqual(frappe.utils.get_datetime(self.server.modified), frappe.utils.get_datetime(modified))
		self.assertNotIn(
			"server_state_changed", [call.args[0] for call in published.call_args_list if call.args]
		)

	def test_a_report_keeps_a_write_made_since_the_record_was_loaded(self):
		frappe.db.set_value("Virtual Machine", self.server.name, "public_ipv4", "203.0.113.9")

		self.server.record_observed_state({"status": "Stopped"}, frappe.utils.now_datetime())

		self.assertEqual(self.server.public_ipv4, "203.0.113.9")
		self.assertEqual(
			frappe.db.get_value("Virtual Machine", self.server.name, "public_ipv4"), "203.0.113.9"
		)
