from unittest.mock import patch

import frappe

from central.api import pilot
from central.api.servers import registry
from central.api.snapshots import take_snapshot
from central.infrastructure.doctype.github_connection.github_connection import GitHubConnectionAttempt
from central.integrations.servers import get_console_url
from central.services.api import ai, storage
from central.signups.access import require_service_access
from central.tests.test_team_management import create_user
from central.tests.test_trial_lifecycle import TrialOnAMachine

LOCKED = "Server access is not part of the free trial"
SERVICE_LOCKED = "LLM and object storage are not part of the free trial"


class TestTrialServerAccess(TrialOnAMachine):
	"""An open free trial gives its owner the site, not the server, until the trial converts."""

	def setUp(self):
		super().setUp()
		self.member = create_user(f"member-{frappe.generate_hash(length=8)}@example.test")
		self.team.append(
			"members", {"user": self.member, "role": "Admin", "resource_type": "*", "status": "Active"}
		)
		self.team.save()

	def machine(self):
		return frappe.get_doc("Virtual Machine", self.server.name)

	def test_an_open_trial_refuses_ssh_keys_the_console_and_pilot(self):
		with self.set_user(self.member):
			for open_access in (
				lambda: self.machine().set_ssh_keys([]),
				lambda: get_console_url(self.machine(), "ssh"),
				lambda: self.machine().get_bench_login_url(self.member),
			):
				with self.assertRaisesRegex(frappe.PermissionError, LOCKED):
					open_access()

	def test_an_open_trial_refuses_a_snapshot(self):
		with self.set_user(self.member), self.assertRaisesRegex(frappe.PermissionError, LOCKED):
			take_snapshot(self.team.name, self.server.name)

	def test_an_open_trial_refuses_termination_protection(self):
		with (
			self.set_user(self.member),
			patch("central.integrations.servers.set_termination_protection") as protect,
			self.assertRaisesRegex(frappe.PermissionError, LOCKED),
		):
			self.machine().set_termination_protection(True)

		protect.assert_not_called()

	def test_the_daily_snapshot_skips_an_open_trial(self):
		from central.infrastructure.doctype.vm_snapshot import vm_snapshot

		frappe.db.set_value("Region", self.server.region, "automatic_snapshots", 1)
		frappe.db.set_value("Virtual Machine", self.server.name, "status", "Running")
		with patch.object(vm_snapshot, "_take_automatic_snapshot") as take:
			vm_snapshot.take_automatic_snapshots()
			take.assert_not_called()

			self.site().db_set("trial_state", "Converted")
			vm_snapshot.take_automatic_snapshots()

		self.assertEqual([call.args[0].name for call in take.call_args_list], [self.server.name])

	def test_an_ended_trial_stays_locked(self):
		self.site().db_set("trial_state", "Ended")

		self.assertTrue(self.machine().is_access_locked())

	def test_a_trial_server_is_locked_before_its_site_is_recorded(self):
		frappe.db.delete("Site", {"server": self.server.name})
		self.assertTrue(self.machine().is_access_locked())

		frappe.db.set_value("Resource Action", {"server": self.server.name}, "is_free_trial", 0)
		self.assertFalse(self.machine().is_access_locked())

	def test_a_converted_trial_opens_server_access(self):
		self.site().db_set("trial_state", "Converted")

		self.assertFalse(self.machine().is_access_locked())
		with self.set_user(self.member):
			self.machine().require_server_access(self.member)

	def test_the_desk_form_shows_the_lock(self):
		machine = self.machine()
		machine.run_method("onload")

		self.assertTrue(machine.get_onload().is_access_locked)

	def test_an_operator_keeps_server_access(self):
		self.machine().require_server_access("Administrator")

	def test_github_connect_is_refused_on_an_open_trial(self):
		attempt = GitHubConnectionAttempt.start(self.credential(), "https://bench.example.test")

		with self.assertRaisesRegex(frappe.PermissionError, LOCKED):
			attempt.bind(self.member)

	def test_the_console_hides_server_access_on_a_trial_server(self):
		with self.set_user(self.member):
			servers = registry(self.team.name)["servers"]

		self.assertTrue(servers[0]["is_access_locked"])

	def test_pilot_reads_whether_its_server_is_locked(self):
		token = self.enroll()

		with patch("frappe.get_request_header", return_value=token):
			self.assertTrue(pilot.get_server_access()["is_locked"])
			self.site().db_set("trial_state", "Converted")
			self.assertFalse(pilot.get_server_access()["is_locked"])

	def test_an_open_trial_refuses_llm_and_buckets(self):
		team = self.team.name
		with self.set_user(self.member):
			for create in (
				lambda: ai.enable_ai(team=team),
				lambda: storage.create_bucket(team=team, bucket_name="files", region=self.region.name),
			):
				with self.assertRaisesRegex(frappe.PermissionError, SERVICE_LOCKED):
					create()

	def test_a_converted_trial_or_an_operator_gets_llm_and_buckets(self):
		require_service_access(self.team.name)

		self.site().db_set("trial_state", "Converted")
		with self.set_user(self.member):
			require_service_access(self.team.name)

	def credential(self):
		return frappe.get_doc("Pilot Credential", {"server": self.server.name, "status": "Active"})
