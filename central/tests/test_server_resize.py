from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import UnitTestCase

from central.errors import AtlasConnectionError
from central.integrations.servers import resize_server

SHAPE = {"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 50}


class TestServerResize(UnitTestCase):
	def setUp(self):
		self.asset = SimpleNamespace(atlas_vm_id="vm-00001")
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

	def test_compute_change_stops_resizes_grows_disk_and_starts(self):
		self.client.get_vm.side_effect = [
			self.remote("running"),
			self.remote("running"),
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("running"),
		]

		resize_server(self.asset, SHAPE)

		self.assertEqual(
			self.client.vm_action.call_args_list, [call("vm-00001", "stop"), call("vm-00001", "start")]
		)
		self.client.update_compute.assert_called_once_with("vm-00001", 2000, 4096, sleep_after_idle_seconds=0)
		self.client.update_disk.assert_called_once_with("vm-00001", 51200)
		self.observe.assert_called_once_with(self.asset)

	def test_disk_only_change_keeps_a_running_server_up(self):
		self.client.get_vm.return_value = self.remote("running", 2000, 4096)

		resize_server(self.asset, SHAPE)

		self.client.vm_action.assert_not_called()
		self.client.update_compute.assert_not_called()
		self.client.update_disk.assert_called_once_with("vm-00001", 51200)

	def test_a_resize_ends_idle_sleep_without_stopping_the_server(self):
		"""A resized server has outgrown the hobby sleep, and Atlas takes the timeout on
		its own while the server runs."""
		self.client.get_vm.return_value = self.remote("running", 2000, 4096, sleep_after_idle_seconds=1800)

		resize_server(self.asset, SHAPE)

		self.client.vm_action.assert_not_called()
		self.client.update_compute.assert_called_once_with("vm-00001", 2000, 4096, sleep_after_idle_seconds=0)

	def test_stopped_server_is_started_after_resize(self):
		self.client.get_vm.side_effect = [
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("stopped"),
			self.remote("running"),
		]

		resize_server(self.asset, SHAPE)

		self.client.vm_action.assert_called_once_with("vm-00001", "start")
		self.client.update_compute.assert_called_once_with("vm-00001", 2000, 4096, sleep_after_idle_seconds=0)

	def test_server_that_never_stops_is_not_resized(self):
		self.client.get_vm.return_value = self.remote("running")

		with (
			patch("central.integrations.servers.time.monotonic", side_effect=[0, 1000]),
			self.assertRaises(AtlasConnectionError),
		):
			resize_server(self.asset, SHAPE)

		self.client.update_compute.assert_not_called()
		self.client.update_disk.assert_not_called()


class TestReshapeVm(UnitTestCase):
	def test_server_that_is_not_ready_is_refused(self):
		from central.billing.catalog.subscriptions import _reshape_vm

		with (
			patch("central.integrations.servers.resize_server") as resize,
			self.assertRaises(frappe.ValidationError),
		):
			_reshape_vm("server-1", "par-2", "Provisioning", SHAPE)

		resize.assert_not_called()
