from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from frappe.tests import IntegrationTestCase
from frappe.utils import get_system_timezone

from central.api.servers import _metrics_window, server_metrics, server_overview
from central.errors import AtlasConnectionError
from central.integrations.servers import get_cached_metrics, get_metric_points
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

START = datetime(2026, 10, 1, tzinfo=UTC)


class TestServerOverview(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("overview.owner@example.test")
		self.viewer = ensure_user("overview.viewer@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Overview Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()
		self.addCleanup(self.team.delete, ignore_permissions=True, force=True)

		self.region = "blr-overview"
		ensure_atlas_instance(self.region)

		self.resource_id = f"vm-overview-{frappe.generate_hash(length=8)}"
		self.atlas_vm_id = f"vm-{frappe.generate_hash(length=8)}"
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": self.resource_id,
				"title": "Overview server",
				"team": self.team.name,
				"region": self.region,
				"status": "Running",
				"vcpus": 2,
				"memory_megabytes": 4096,
				"disk_gigabytes": 40,
				"public_ipv4": "203.0.113.10",
				"atlas_vm_id": self.atlas_vm_id,
			}
		).insert()
		self.addCleanup(self.server.delete, ignore_permissions=True, force=True)

		self.cache_key = f"atlas:metrics:{self.server.name}:{int(START.timestamp())}:now"
		frappe.cache.delete_value(self.cache_key)
		self.addCleanup(frappe.cache.delete_value, self.cache_key)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_viewer_gets_static_server_data(self):
		frappe.set_user(self.viewer)
		try:
			result = server_overview(team=self.team.name, resource_id=self.server.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["server"]["title"], "Overview server")
		self.assertEqual(result["server"]["region"], self.region)
		self.assertEqual(result["server"]["region_details"]["display_name"], self.region)
		self.assertEqual(result["server"]["public_ipv4"], "203.0.113.10")
		self.assertIsNone(result["server"]["plan_title"])
		self.assertIsNone(result["server"]["plan_rate"])
		self.assertEqual(result["server"]["plan_currency"], "INR")
		self.assertNotIn("monitoring", result)

	def test_overview_lists_the_keys_the_server_was_created_with(self):
		with patch("central.infrastructure.doctype.team_ssh_key.team_ssh_key.TeamSSHKey.queue_sync"):
			key = frappe.get_doc(
				{
					"doctype": "Team SSH Key",
					"team": self.team.name,
					"title": "Laptop",
					"public_key": make_public_key(),
				}
			).insert()
		self.server.append("ssh_keys", {"team_ssh_key": key.name})
		self.server.save()
		self.addCleanup(key.delete, ignore_permissions=True, force=True)
		self.addCleanup(frappe.db.delete, "Server SSH Key", {"parent": self.server.name})

		frappe.set_user(self.viewer)
		try:
			keys = server_overview(team=self.team.name, resource_id=self.server.name)["server"]["ssh_keys"]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(keys, [{"title": "Laptop", "fingerprint": key.fingerprint}])

	def test_viewer_gets_region_metrics(self):
		metrics = {"available": True, "points": [], "sample_interval_seconds": 300}
		frappe.set_user(self.viewer)
		try:
			with patch("central.api.servers.get_cached_metrics", return_value=metrics) as get:
				result = server_metrics(team=self.team.name, resource_id=self.server.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result, metrics)
		self.assertEqual(get.call_args.args[0].atlas_vm_id, self.atlas_vm_id)
		self.assertIsNone(get.call_args.args[2])

	def test_stopped_server_has_no_metrics_and_skips_atlas(self):
		self.server.db_set("status", "Stopped")
		frappe.set_user(self.viewer)
		try:
			with patch("central.api.servers.get_cached_metrics") as get:
				result = server_metrics(team=self.team.name, resource_id=self.server.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result, {"available": False})
		get.assert_not_called()

	def test_metrics_cache_avoids_a_second_atlas_request(self):
		with patch("central.integrations.servers.get_client") as get_client:
			get_client.return_value.get_vm_metrics.return_value = {
				"samples": [make_sample(0, 0, 0), make_sample(300, 300_000_000, 300_000)],
				"sample_interval_seconds": 300,
			}

			first = get_cached_metrics(self.server, START)
			second = get_cached_metrics(self.server, START)

		self.assertTrue(first["available"])
		self.assertEqual(first["sample_interval_seconds"], 300)
		self.assertEqual(second, first)
		get_client.return_value.get_vm_metrics.assert_called_once()

	def test_an_unavailable_metrics_log_holds_no_frame_locals(self):
		def refuse(*args, **kwargs):
			headers = {"Authorization": "Bearer bearer-marker-" + frappe.generate_hash(length=8)}
			raise AtlasConnectionError(f"down {len(headers)}")

		with patch("central.integrations.servers.get_client") as get_client:
			get_client.return_value.get_vm_metrics.side_effect = refuse
			self.assertEqual(get_cached_metrics(self.server, START), {"available": False})

		logged = frappe.get_last_doc("Error Log", filters={"method": ("like", "Atlas metrics unavailable:%")})
		self.assertIn("AtlasConnectionError", logged.error)
		self.assertNotIn("bearer-marker-", logged.error)

	def test_preset_period_runs_until_now(self):
		start, end = _metrics_window("7d", None, None)

		self.assertAlmostEqual(
			(datetime.now(UTC) - start).total_seconds(), timedelta(days=7).total_seconds(), delta=60
		)
		self.assertIsNone(end)

	def test_custom_window_reads_the_site_clock(self):
		start, end = _metrics_window("custom", "2026-10-08 10:00:00", "2026-10-08 11:00:00")

		timezone = ZoneInfo(get_system_timezone())
		self.assertEqual(start, datetime(2026, 10, 8, 10, tzinfo=timezone))
		self.assertEqual(end, datetime(2026, 10, 8, 11, tzinfo=timezone))

	def test_invalid_windows_are_rejected(self):
		for period, start, end in [
			("1y", None, None),
			("custom", None, "2026-10-08 11:00:00"),
			("custom", "2026-10-08 11:00:00", "2026-10-08 10:00:00"),
			("custom", "2026-09-01 00:00:00", "2026-10-08 00:00:00"),
			("custom", "yesterday", "2026-10-08 00:00:00"),
		]:
			with self.subTest(period=period, start=start), self.assertRaises(frappe.ValidationError):
				_metrics_window(period, start, end)

	def test_custom_window_is_sent_to_atlas(self):
		start, end = _metrics_window("custom", "2026-10-08 10:00:00", "2026-10-08 11:00:00")
		self.addCleanup(
			frappe.cache.delete_value,
			f"atlas:metrics:{self.server.name}:{int(start.timestamp())}:{int(end.timestamp())}",
		)
		with patch("central.integrations.servers.get_client") as get_client:
			get_client.return_value.get_vm_metrics.return_value = {
				"samples": [],
				"sample_interval_seconds": 20,
			}

			result = get_cached_metrics(self.server, start, end)

		get_client.return_value.get_vm_metrics.assert_called_once_with(self.atlas_vm_id, start, end)
		self.assertEqual(result["sample_interval_seconds"], 20)

	def test_unknown_period_is_rejected_before_atlas(self):
		frappe.set_user(self.viewer)
		try:
			with (
				patch("central.api.servers.get_cached_metrics") as get,
				self.assertRaises(frappe.ValidationError),
			):
				server_metrics(team=self.team.name, resource_id=self.server.name, period="1y")
		finally:
			frappe.set_user("Administrator")

		get.assert_not_called()

	def test_atlas_failure_marks_metrics_unavailable(self):
		with (
			patch("central.integrations.servers.get_client") as get_client,
			patch("central.integrations.servers.frappe.log_error") as log_error,
		):
			get_client.return_value.get_vm_metrics.side_effect = AtlasConnectionError

			result = get_cached_metrics(self.server, START)

		self.assertEqual(result, {"available": False})
		log_error.assert_called_once()

	def test_unknown_atlas_response_fails_loudly(self):
		with (
			patch("central.integrations.servers.get_client") as get_client,
			self.assertRaises(KeyError),
		):
			get_client.return_value.get_vm_metrics.return_value = {"points": []}

			get_cached_metrics(self.server, START)

	def test_metric_points_turn_counters_into_rates(self):
		# 2 vCPUs busy for half of 300 seconds is 300 million CPU microseconds.
		points = get_metric_points([make_sample(0, 0, 0), make_sample(300, 300_000_000, 300_000)], vcpus=2)

		self.assertEqual(len(points), 1)
		self.assertEqual(points[0]["time"], 300)
		self.assertEqual(points[0]["cpu_percent"], 50)
		self.assertEqual(points[0]["received_bytes_per_second"], 1000)
		self.assertEqual(points[0]["disk_used_bytes"], 1024 * 1024 * 1024)

	def test_reboot_or_down_sample_has_no_rate(self):
		reboot = make_sample(600, 1_000, 10)
		down = make_sample(900, 2_000, 20, up=False)

		points = get_metric_points([make_sample(300, 300_000_000, 300_000), reboot, down], vcpus=2)

		self.assertIsNone(points[0]["cpu_percent"])
		self.assertIsNone(points[0]["received_bytes_per_second"])
		self.assertIsNone(points[1]["cpu_percent"])
		self.assertFalse(points[1]["is_up"])


def make_sample(timestamp: int, cpu_microseconds: int, received_bytes: int, up: bool = True) -> dict:
	return {
		"timestamp": timestamp,
		"up": up,
		"compute": {"cpu_microseconds": cpu_microseconds, "memory_bytes": 512 * 1024 * 1024},
		"disk": {
			"size_mib": 8192,
			"used_mib": 1024,
			"read_bytes_per_second": 0,
			"write_bytes_per_second": 100,
		},
		"network": {"received_bytes": received_bytes, "sent_bytes": 0},
	}


def make_public_key() -> str:
	public_key = Ed25519PrivateKey.generate().public_key()
	return public_key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
