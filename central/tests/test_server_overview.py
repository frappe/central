from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import server_overview
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.pilot import PilotMonitoringClient, get_cached_monitoring
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_region


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
		ensure_region(self.region)
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()

		self.resource_id = f"vm-overview-{frappe.generate_hash(length=8)}"
		self.gateway_url = f"https://{self.resource_id}.example.test"
		self.audience_id = f"pcred-{self.resource_id}"
		self.asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": self.resource_id,
				"title": "Overview server",
				"team": self.team.name,
				"cluster": self.region,
				"status": "Running",
				"vcpus": 2,
				"memory_megabytes": 4096,
				"disk_gigabytes": 40,
				"public_ipv4": "203.0.113.10",
				"gateway_url": self.gateway_url,
			}
		).insert()
		self.addCleanup(self.asset.delete, ignore_permissions=True, force=True)

		PilotCredential.mint(
			team=self.team.name,
			pilot_credential_id=self.audience_id,
			asset=self.asset.name,
			audience_id=self.audience_id,
		)
		self.addCleanup(
			lambda: frappe.db.exists("Pilot Credential", self.audience_id)
			and frappe.delete_doc("Pilot Credential", self.audience_id, ignore_permissions=True, force=True)
		)
		frappe.cache.delete_value(f"pilot:monitoring:{self.resource_id}")
		self.addCleanup(frappe.cache.delete_value, f"pilot:monitoring:{self.resource_id}")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_viewer_gets_static_server_data_and_cached_pilot_monitoring(self):
		monitoring = {"available": True, "current": {"cpu_percent": 18}, "history": {"system": {}}}
		frappe.set_user(self.viewer)
		try:
			with patch("central.integrations.pilot.get_cached_monitoring", return_value=monitoring) as get:
				result = server_overview(team=self.team.name, resource_id=self.asset.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["server"]["title"], "Overview server")
		self.assertEqual(result["server"]["public_ipv4"], "203.0.113.10")
		self.assertIsNone(result["server"]["plan_title"])
		self.assertIsNone(result["server"]["plan_rate"])
		self.assertEqual(result["server"]["plan_currency"], "INR")
		self.assertEqual(result["monitoring"], monitoring)
		get.assert_called_once_with(self.resource_id, self.gateway_url, self.audience_id)

	def test_stopped_server_returns_static_data_without_calling_pilot(self):
		self.asset.db_set("status", "Stopped")
		frappe.set_user(self.viewer)
		try:
			with patch("central.integrations.pilot.get_cached_monitoring") as get:
				result = server_overview(team=self.team.name, resource_id=self.asset.name)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(result["monitoring"]["available"])
		get.assert_not_called()

	def test_monitoring_cache_avoids_a_second_pilot_request(self):
		with patch("central.integrations.pilot.PilotMonitoringClient") as client:
			client.return_value.get_overview.return_value = {
				"current": {"cpu_percent": 18},
				"history": {"system": {"points": []}},
			}

			first = get_cached_monitoring(self.resource_id, self.gateway_url, "audience")
			second = get_cached_monitoring(self.resource_id, self.gateway_url, "audience")

		self.assertTrue(first["available"])
		self.assertEqual(second, first)
		client.assert_called_once_with(self.gateway_url, "audience")
		client.return_value.get_overview.assert_called_once_with()

	def test_overview_fetches_metrics_and_history_in_parallel(self):
		def fake_get(url, **kwargs):
			response = MagicMock()
			if url.endswith("/api/v1/metrics"):
				response.json.return_value = {"cpu_percent": 18}
			else:
				response.json.return_value = {"system": {"points": [{"time": 1, "Load1": 0.1}]}}
			return response

		with (
			patch("central.integrations.pilot.mint_bench_login", return_value="signed-token"),
			patch("central.integrations.pilot.requests.get", side_effect=fake_get) as get,
		):
			result = PilotMonitoringClient(self.gateway_url, "audience").get_overview()

		self.assertEqual(result["current"], {"cpu_percent": 18})
		self.assertEqual(result["history"]["system"]["points"][0]["Load1"], 0.1)
		self.assertEqual(get.call_count, 2)

	def test_metrics_client_uses_a_central_signed_bearer_token(self):
		response = MagicMock()
		response.json.return_value = {"cpu_percent": 18}
		with (
			patch("central.integrations.pilot.mint_bench_login", return_value="signed-token"),
			patch("central.integrations.pilot.requests.get", return_value=response) as get,
		):
			result = PilotMonitoringClient(self.gateway_url, "audience").get_metrics()

		self.assertEqual(result, {"cpu_percent": 18})
		get.assert_called_once_with(
			f"{self.gateway_url}/api/v1/metrics",
			headers={"Authorization": "Bearer signed-token"},
			params=None,
			timeout=3,
			allow_redirects=False,
		)
		response.raise_for_status.assert_called_once_with()
