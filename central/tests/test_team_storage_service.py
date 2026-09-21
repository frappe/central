import json
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from central.integrations.server_provisioning import _create_payload, _get_team_storage_service

STORAGE_CONFIG = {
	"access_key": "access",
	"secret_key": "secret",
	"bucket": "team-42-in-mumbai-backups",
	"provider": "garage",
	"region": "in-mumbai",
	"endpoint_url": "https://s3.in-mumbai.example.test",
}


def storage_service(name="team-service-1"):
	service = Mock(
		access_key="access",
		bucket_name="team-42-in-mumbai-backups",
		region="in-mumbai",
		endpoint_url="https://s3.in-mumbai.example.test",
	)
	service.name = name
	service.get_password.return_value = "secret"
	return service


def pilot_request():
	request = Mock(team="TEAM-00001")
	request.name = "action-1"
	request.get_configuration.return_value = Mock(
		image_id="image-1",
		virtual_cpu_count=2,
		memory_mib=4096,
		disk_mib=10240,
		hostname="pilot-1",
		ssh_keys=[],
		image_tags={"purpose": "pilot"},
	)
	return request


class TestTeamStorageService(TestCase):
	def test_reuses_active_storage_service_in_the_same_region(self):
		request = Mock(team="TEAM-00001", atlas_instance="atlas-mumbai")
		service_doc = storage_service("service-1")

		with (
			patch(
				"central.integrations.server_provisioning.frappe.db.get_value",
				side_effect=[
					"in-mumbai",
					"TEAM-00001",
					frappe._dict(name="service-1", status="Active"),
				],
			) as get_value,
			patch("central.integrations.server_provisioning.frappe.get_doc", return_value=service_doc),
		):
			configuration = _get_team_storage_service(request)

		self.assertEqual(configuration, STORAGE_CONFIG)
		self.assertEqual(
			get_value.call_args_list[1].args,
			("Team", "TEAM-00001", "name"),
		)
		self.assertTrue(get_value.call_args_list[1].kwargs["for_update"])
		self.assertEqual(
			get_value.call_args_list[2].args,
			(
				"Team Service",
				{"team": "TEAM-00001", "add_on_service": "storage", "region": "in-mumbai"},
				["name", "status"],
			),
		)

	def test_creates_bucket_before_subscription_and_team_service(self):
		request = Mock(team="TEAM-00001", atlas_instance="atlas-mumbai", requested_by="Administrator")
		team_service = storage_service()
		team_service.insert.return_value = team_service

		def get_value(doctype, filters, *args, **kwargs):
			if doctype == "Atlas Instance":
				return "in-mumbai"
			if doctype == "Team Service":
				return None
			if doctype == "Team":
				return 42
			if doctype == "Plan":
				return "storage-plan"
			raise AssertionError(f"Unexpected lookup: {doctype}")

		order = []
		storage_client = Mock()
		storage_client.create_bucket.side_effect = lambda name: (
			order.append("bucket")
			or {
				"name": name,
				"region": "in-mumbai",
				"credentials": {"access_key": "access", "secret_access_key": "secret"},
			}
		)
		subscribe = Mock(
			side_effect=lambda *args, **kwargs: order.append("subscription")
			or {"subscription": "subscription-1"}
		)
		team_service.insert.side_effect = lambda **kwargs: order.append("team-service") or team_service

		with (
			patch("central.integrations.server_provisioning.frappe.db.get_value", side_effect=get_value),
			patch("central.integrations.server_provisioning.frappe.db.exists", return_value=True),
			patch("central.integrations.server_provisioning.frappe.db.savepoint"),
			patch("central.integrations.server_provisioning.ObjectStorageClient") as client_class,
			patch("central.integrations.server_provisioning.ServiceDetail") as service_detail,
			patch("central.integrations.server_provisioning.provision_service_subscription", subscribe),
			patch(
				"central.integrations.server_provisioning.frappe.get_doc", return_value=team_service
			) as get_doc,
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = "https://s3.in-mumbai.example.test"
			configuration = _get_team_storage_service(request)

		self.assertEqual(configuration, STORAGE_CONFIG)
		self.assertEqual(order, ["bucket", "subscription", "team-service"])
		storage_client.create_bucket.assert_called_once_with("team-42-in-mumbai-backups")
		subscribe.assert_called_once_with(
			"TEAM-00001", "storage-plan", cluster="atlas-mumbai", changed_by="Administrator"
		)
		get_doc.assert_called_once_with(
			{
				"doctype": "Team Service",
				"team": "TEAM-00001",
				"add_on_service": "storage",
				"subscription": "subscription-1",
				"region": "in-mumbai",
				"status": "Active",
				"bucket_name": "team-42-in-mumbai-backups",
				"endpoint_url": "https://s3.in-mumbai.example.test",
				"access_key": "access",
				"secret_access_key": "secret",
			}
		)

	def test_does_not_provision_when_the_locked_read_finds_a_service(self):
		request = Mock(team="TEAM-00001", atlas_instance="atlas-mumbai")
		service_doc = storage_service("service-created-by-peer")

		with (
			patch(
				"central.integrations.server_provisioning.frappe.db.get_value",
				side_effect=[
					"in-mumbai",
					"TEAM-00001",
					frappe._dict(name="service-created-by-peer", status="Active"),
				],
			),
			patch("central.integrations.server_provisioning.frappe.get_doc", return_value=service_doc),
			patch("central.integrations.server_provisioning.ObjectStorageClient") as storage_client,
		):
			configuration = _get_team_storage_service(request)

		self.assertEqual(configuration, STORAGE_CONFIG)
		storage_client.assert_not_called()

	def test_deletes_new_bucket_when_local_records_fail(self):
		request = Mock(team="TEAM-00001", atlas_instance="atlas-mumbai", requested_by="Administrator")

		def get_value(doctype, filters, *args, **kwargs):
			return {
				"Atlas Instance": "in-mumbai",
				"Team Service": None,
				"Team": 42,
				"Plan": "storage-plan",
			}[doctype]

		storage_client = Mock()
		storage_client.create_bucket.return_value = {
			"name": "team-42-in-mumbai-backups",
			"region": "in-mumbai",
			"credentials": {"access_key": "access", "secret_access_key": "secret"},
		}

		with (
			patch("central.integrations.server_provisioning.frappe.db.get_value", side_effect=get_value),
			patch("central.integrations.server_provisioning.frappe.db.exists", return_value=True),
			patch("central.integrations.server_provisioning.frappe.db.savepoint"),
			patch("central.integrations.server_provisioning.frappe.db.rollback") as rollback,
			patch("central.integrations.server_provisioning.ObjectStorageClient") as client_class,
			patch("central.integrations.server_provisioning.ServiceDetail") as service_detail,
			patch(
				"central.integrations.server_provisioning.provision_service_subscription",
				side_effect=RuntimeError("billing failed"),
			),
			self.assertRaisesRegex(RuntimeError, "billing failed"),
		):
			client_class.from_region.return_value = storage_client
			service_detail.endpoint_for.return_value = "https://s3.in-mumbai.example.test"
			_get_team_storage_service(request)

		storage_client.delete_bucket.assert_called_once_with("team-42-in-mumbai-backups")
		rollback.assert_called_once_with(save_point="team_storage_provisioning")

	def test_pilot_payload_contains_the_team_storage_configuration(self):
		request = pilot_request()

		with (
			patch("central.integrations.server_provisioning.PilotCredential.mint", return_value="token"),
			patch(
				"central.integrations.server_provisioning.central_url", return_value="https://central.test"
			),
			patch(
				"central.integrations.server_provisioning.jwks_url",
				return_value="https://central.test/jwks",
			),
			patch(
				"central.integrations.server_provisioning._get_team_storage_service",
				return_value=STORAGE_CONFIG,
			),
		):
			payload = _create_payload(request)

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertEqual(metadata["s3"], STORAGE_CONFIG)

	def test_storage_failure_does_not_block_pilot_creation(self):
		request = pilot_request()

		with (
			patch("central.integrations.server_provisioning.PilotCredential.mint", return_value="token"),
			patch(
				"central.integrations.server_provisioning.central_url", return_value="https://central.test"
			),
			patch(
				"central.integrations.server_provisioning.jwks_url",
				return_value="https://central.test/jwks",
			),
			patch(
				"central.integrations.server_provisioning._get_team_storage_service",
				side_effect=RuntimeError("storage unavailable"),
			),
			patch("central.integrations.server_provisioning.frappe.log_error") as log_error,
		):
			payload = _create_payload(request)

		metadata = json.loads(payload["metadata"]["pilot-central"])
		self.assertNotIn("s3", metadata)
		log_error.assert_called_once()
