from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import UnitTestCase

from central.errors import AtlasConnectionError
from central.integrations.servers import resize_server

SHAPE = {"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 50}


class TestServerResize(UnitTestCase):
	def setUp(self):
		self.server = SimpleNamespace(atlas_vm_id="vm-00001")
		self.client = MagicMock()
		self.enterContext(patch("central.integrations.servers._client", return_value=self.client))
		self.observe = self.enterContext(patch("central.integrations.servers.observe_server"))
		self.enterContext(patch("central.integrations.servers.time.sleep"))

	def remote(
		self,
		state: str,
		cpu_millicores: int = 1000,
		memory_mib: int = 2048,
		disk_mib: int = 25600,
		sleep_after_idle_seconds: int = 0,
	):
		return {
			"current_state": state,
			"compute": {
				"cpu_millicores": cpu_millicores,
				"memory_mib": memory_mib,
				"sleep_after_idle_seconds": sleep_after_idle_seconds,
			},
			"disk": {"size_mib": disk_mib},
		}

	def test_compute_change_stops_resizes_and_starts(self):
		"""A CPU or memory change stops the VM, resizes CPU, memory and disk in one call, then
		starts it again."""
		self.client.get_vm.side_effect = [
			self.remote("running"),
			self.remote("running"),
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("running"),
		]

		resize_server(self.server, SHAPE)

		self.assertEqual(
			self.client.vm_action.call_args_list, [call("vm-00001", "stop"), call("vm-00001", "start")]
		)
		self.client.resize.assert_called_once_with("vm-00001", 2000, 4096, 51200)
		self.client.update_disk.assert_not_called()
		self.observe.assert_called_once_with(self.server)

	def test_disk_only_grow_is_online_and_keeps_the_server_up(self):
		"""Disk grows through the online disk API, so the server is neither stopped nor resized."""
		self.client.get_vm.return_value = self.remote("running", 2000, 4096)

		resize_server(self.server, SHAPE)

		self.client.vm_action.assert_not_called()
		self.client.resize.assert_not_called()
		self.client.update_disk.assert_called_once_with("vm-00001", 51200)

	def test_a_resize_ends_idle_sleep_without_stopping_the_server(self):
		"""Clearing the idle timeout alone needs no stop: Atlas takes it in any state."""
		self.client.get_vm.return_value = self.remote(
			"running", 2000, 4096, 51200, sleep_after_idle_seconds=1800
		)

		resize_server(self.server, SHAPE)

		self.client.vm_action.assert_not_called()
		self.client.resize.assert_called_once_with("vm-00001", 2000, 4096, 51200)

	def test_disk_only_grow_on_a_sleeping_server_stays_online(self):
		"""The disk grows online first, so the resize that ends idle sleep changes no resources
		and Atlas takes it on a running server."""
		self.client.get_vm.return_value = self.remote("running", 2000, 4096, sleep_after_idle_seconds=1800)

		resize_server(self.server, SHAPE)

		self.client.vm_action.assert_not_called()
		self.client.update_disk.assert_called_once_with("vm-00001", 51200)
		self.client.resize.assert_called_once_with("vm-00001", 2000, 4096, 51200)
		calls = [name for name, _, _ in self.client.mock_calls if name in ("update_disk", "resize")]
		self.assertEqual(calls, ["update_disk", "resize"])

	def test_stopped_server_is_resized_then_started(self):
		self.client.get_vm.side_effect = [
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("running"),
		]

		resize_server(self.server, SHAPE)

		self.client.vm_action.assert_called_once_with("vm-00001", "start")
		self.client.resize.assert_called_once_with("vm-00001", 2000, 4096, 51200)

	def test_a_migrating_server_is_not_told_to_change_power(self):
		"""Atlas may move the VM to another host during a resize. Central waits it out and
		never sends a power action while it is migrating."""
		self.client.get_vm.side_effect = [
			self.remote("running"),
			self.remote("running"),
			self.remote("stopped"),
			self.remote("migrating"),
			self.remote("stopped"),
			self.remote("running"),
		]

		resize_server(self.server, SHAPE)

		self.assertEqual(
			self.client.vm_action.call_args_list, [call("vm-00001", "stop"), call("vm-00001", "start")]
		)
		self.client.resize.assert_called_once_with("vm-00001", 2000, 4096, 51200)

	def test_server_that_never_stops_times_out(self):
		self.client.get_vm.return_value = self.remote("running")

		with (
			patch("central.integrations.servers.time.monotonic", side_effect=[0, 1000]),
			self.assertRaises(AtlasConnectionError),
		):
			resize_server(self.server, SHAPE)

		self.client.resize.assert_not_called()
		self.client.update_disk.assert_not_called()


class TestConsoleResize(UnitTestCase):
	def test_resize_is_gated_and_handed_to_billing(self):
		from central.api.servers import resize_server

		begin = self.enterContext(
			patch(
				"central.billing.catalog.subscriptions.begin_resize",
				return_value={"queued": True, "resized": True},
			)
		)
		self.enterContext(patch("central.utils.guards.resolve_team", return_value="TEAM-1"))
		self.enterContext(patch("central.utils.guards.can", return_value=True))
		self.enterContext(patch("central.utils.guards.frappe.session", user="user@example.com"))

		def get_value(doctype, filters, field):
			if doctype == "Virtual Machine":
				return "server-1"
			if doctype == "Subscription":
				return "SUB-1"
			raise AssertionError(doctype)

		self.enterContext(patch("central.api.servers.frappe.db.get_value", side_effect=get_value))

		result = resize_server(team="TEAM-1", resource_id="server-1", plan="plan-2vcpu", disk_gigabytes="20")

		self.assertEqual(result["queued"], True)
		begin.assert_called_once_with(
			"SUB-1", plan="plan-2vcpu", includes=None, sub_category=None, disk_gigabytes=20
		)

	def test_resize_without_the_capability_is_refused(self):
		from central.api.servers import resize_server

		self.enterContext(patch("central.utils.guards.resolve_team", return_value="TEAM-1"))
		self.enterContext(patch("central.utils.guards.can", return_value=False))
		self.enterContext(patch("central.utils.guards.frappe.session", user="user@example.com"))

		with self.assertRaises(frappe.PermissionError):
			resize_server(team="TEAM-1", resource_id="server-1", plan="plan-2vcpu", disk_gigabytes=20)
